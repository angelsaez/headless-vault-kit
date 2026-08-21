---
key: value
  bad indentation: here
unclosed: "quote
---

# Malformed YAML

Parsing must fail for this file without taking the scan down, and the failure must be
recorded so that it can be reported.
