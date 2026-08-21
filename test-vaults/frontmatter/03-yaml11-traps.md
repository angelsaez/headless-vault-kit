---
answer_no: no
answer_yes: yes
switch_on: on
switch_off: off
leading_zero: 0755
sexagesimal: 12:30
version: 1.10
country_code: NO
---

# YAML 1.1 traps

Under YAML 1.1 the first four values are booleans and 0755 is octal. Under YAML 1.2,
which is what Obsidian uses through js-yaml, all of them are strings except the float.
This file is the reason ADR-0001 pins ruamel.yaml instead of PyYAML.
