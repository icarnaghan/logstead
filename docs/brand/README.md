# Brand assets

- `logo-source.svg` is the editable source. It keeps live `<text>` and depends on `system-ui`, so do not ship it.
- `fonts/` holds Inter Bold and SemiBold (v4.0, from the official rsms/inter release) with its SIL OFL license. They are used only to outline text.
- Regenerate the outlined assets from `frontend/`:

```
node scripts/outline-brand-text.mjs
```

This writes `src/assets/brand/brand-paths.ts`, `logo.svg`, and `logo-mark.svg`. The script uses `opentype.js` (dev dependency, pinned) and is not part of `npm run build`.
- If the source artwork changes, update the constants at the top of the script (text positions, sizes, spacing, mark geometry).
