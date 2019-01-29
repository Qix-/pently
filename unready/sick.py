#!/usr/bin/env python3
"""
sick
translate Pently from ca65 to ASM6

Rules for ASM6
- Assembler directives need not have a leading dot.
- equ replaces =; = instead replaces .set
- db or byte replaces .byt
- dw or word replaces .addr
- dsb replaces .res
- rept (with no second argument) replaces .repeat; emulate the second
  argument with =.
- rept 1 replaces .scope
- No .bss; emulate it with .enum and = $. May need host to allocate
  both zero page and BSS memory.
- No other .segment; treat code and read-only data the same.
- No .proc; emulate it by either prefixing the namespace to non-@ labels
  or perhaps wrapping the body in a .rept 1.
- No .assert; emulate it with if.
- No second argument to .assert either, but it can be emulated with if.
- Unnamed labels follow the x816 convention (-, --, +foo), not the ca65
  convention (:). Change them as described below

Anonymous labels should be easier to translate automatically.

- At the start of translation, set a counter to 0.
- When a line's label is :, increase the counter by 1 and then emit a
  label of the form @ca65toasm6_anonlabel_1:.
- Replace :+ in an expression with @ca65toasm6_anonlabel_{anon_labels_seen+1}.
- Replace :- in an expression with @ca65toasm6_anonlabel_{anon_labels_seen}.


"""
import sys
import os
import re
from collections import defaultdict
from itertools import chain

quotesRE = r"""[^"';]+|"[^"]*"|'[^']*'|;.*"""
quotesRE = re.compile(quotesRE)
equateRE = r"""\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)"""
equateRE = re.compile(equateRE)
anonlabelrefRE = r""":([+]+|[-]+)"""
anonlabelrefRE = re.compile(anonlabelrefRE)

def uncomment(line):
    lineparts = quotesRE.findall(line.rstrip())
    if lineparts and lineparts[-1].startswith(";"): del lineparts[-1]
    return "".join(lineparts)

def openreadlines(filename, xform=None):
    with open(filename, "r", encoding="utf-8") as infp:
        return [xform(x) if xform else x for x in infp]

filestoload = [
    "pentlyconfig.inc", "pently.inc", "pentlyseq.inc",
    "pentlysound.s", "../obj/nes/pentlybss.inc", "pentlymusic.s",
]

directive_ignore = {
    'import', 'export', 'importzp', 'exportzp', 'global', 'globalzp',
    'include', 'assert', 'pushseg', 'popseg'
}
    
directive_translation = {
    'if': 'if', 'else': 'else', 'elseif': 'elseif', 'endif': 'endif',
    'ifdef': 'ifdef', 'ifndef': 'ifndef',
    'byt': 'db', 'byte': 'db', 'word': 'dw', 'addr': 'dw', 'res': 'dsb'
}

allfiles = [
    openreadlines(os.path.join("../src", n),
                  lambda x: uncomment(x).strip())
    for n in filestoload
]
specialseg = None
specialseg_lines = defaultdict(list)
inscope = False
lines = []
anon_labels_seen = 0
anon_label_fmt = "@ca65toasm6_anonlabel_%d"
global_equates = []
def resolve_anon_ref(m):
    s = m.group(0)
    distance = len(s) - 2
    if s[1] == '+':
        return anon_label_fmt % (anon_labels_seen + distance + 1)
    elif s[1] == '-':
        return anon_label_fmt % (anon_labels_seen - distance)
    else:
        raise ValueError("unknown anonref %s" % s)

for line in chain(*allfiles):
    if not line: continue
    words = line.split(None, 1)
    label = None

    if ':' in words[0] or (len(words) > 1 and words[1].startswith(':')):
        candidatelabel, candidateline = (s.strip() for s in line.split(':', 1))
        if candidateline.startswith(("+", "-", ":")):
            pass  # actually an anonymous label reference or scope resolution
        else:
            label, line = candidatelabel, candidateline
            if label == '':
                anon_labels_seen += 1
                label = anon_label_fmt % anon_labels_seen
            words = line.split(None, 1)
    else:
        label = None

    # Dot-directives
    if line.startswith('.'):
        word0 = words[0].lower().lstrip('.')
        if word0 in directive_ignore:
            continue
        if word0 == 'zeropage':
            specialseg = 'zeropage'
            continue
        if word0 == 'bss':
            specialseg = 'bss'
            continue
        if word0 == 'segment':
            specialseg = None
            continue
        if word0 == 'scope':
            lines.append('rept 1')
            inscope += 1
            continue
        if word0 == 'proc':
            lines.append('%s: rept 1' % words[1])
            inscope += 1
            continue
        if word0 in ('endscope', 'endproc'):
            lines.append('endr')
            inscope -= 1
            continue
        if word0 == 'define':
            dfnparts = words[1].split(None, 1)
            word0 = dfnparts[0]
            words = [word0, "equ %s" % (dfnparts[1])]
        if word0 in directive_translation:
            words[0] = directive_translation[word0]
            word0 = words[0]
        else:
            print("unknown directive", line, file=sys.stderr)
            continue

    equate = equateRE.match(line)
    if equate:
        label, expr = equate.groups()
        # Not sure if I want EQU or =, as EQU is for string replacement
        # and = is for numbers, but I don't know if = is required to be
        # constant at the time that line is assembled.
        words = [label, "=", expr]
        if not specialseg and not inscope:
            global_equates.append(" ".join(words))
            continue
        label = None

    if len(words) > 1:
        operand = quotesRE.findall(words[1])
        for i in range(len(operand)):
            randpart = operand[i]
            if randpart.startswith(("'", '"')): continue
            randpart = randpart.replace("::", "")
            randpart = anonlabelrefRE.sub(resolve_anon_ref, randpart)
            operand[i] = randpart
        words[1] = operand = "".join(operand)

    line = " ".join(words)
    if label:
        line = "%s: %s" % (label, line)
    if specialseg:
        specialseg_lines[specialseg].append(line)
    else:
        lines.append(line)

print("\n".join(global_equates))
for segment, seglines in specialseg_lines.items():
    print(";;; VARIABLES SEGMENT %s" % segment)
    print("\n".join(seglines))

print("\n".join(lines))