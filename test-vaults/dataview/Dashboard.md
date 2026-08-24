# Dashboard

Two blocks and one that must be ignored.

```dataview
LIST FROM #active
```

```dataview
TABLE status, rating AS "Score" FROM "Projects" WHERE status = "open" SORT rating DESC
```

```dataviewjs
dv.list(dv.pages("#active").file.name)
```
