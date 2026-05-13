# Parity Design System — Lumina Network Ops

Generated from Google Stitch project `9754738190889064258`.

## Color Tokens

| Token | Hex |
|---|---|
| `primary` | `#0059bb` |
| `primary-container` | `#0070ea` |
| `secondary` (success/green) | `#006c4f` |
| `tertiary` (neutral/grey) | `#585c61` |
| `error` (critical/red) | `#ba1a1a` |
| `surface` | `#f8f9fa` |
| `surface-container-low` | `#f3f4f5` |
| `surface-container-lowest` (cards) | `#ffffff` |
| `surface-container-high` | `#e7e8e9` |
| `surface-container-highest` | `#e1e3e4` |
| `on-surface` | `#191c1d` |
| `on-surface-variant` | `#414754` |
| `outline` | `#717786` |
| `outline-variant` | `#c1c6d7` |

## Typography

- Font: **Inter** (all weights 300-800)
- Icons: **Material Symbols Outlined**
- Labels: `text-[10px] font-bold uppercase tracking-widest`
- Hero numbers: `text-6xl font-extrabold`
- Section headings: `text-headline-sm font-bold` or `text-2xl font-extrabold tracking-tight`

## Layout

- **Top nav**: h-16, white bg, sticky, z-40. Brand "Parity" left, nav links center, search + icons + avatar right.
- **Sidebar**: w-64, fixed left, slate-50 bg. Network status at top, nav items with Material icons, support/docs at bottom.
- **Main content**: ml-64, p-8, bg-surface.
- **Detail panels**: Right-side aside (w-96 or w-[380px]), surface-container-low bg.

## Component Patterns

### Cards
- `bg-surface-container-lowest rounded-xl shadow-sm` (or subtle shadow-[0px_24px_48px_rgba(33,37,41,0.04)])
- No borders (use surface-level shifts). Ghost borders only: `border border-outline-variant/10`

### Status Chips
- Success: `bg-secondary/10 text-secondary`
- Warning: `bg-tertiary/10 text-tertiary` or `bg-orange-400/10 text-orange-400`
- Critical: `bg-error/10 text-error`
- Info: `bg-primary/10 text-primary`

### Buttons
- Primary: `bg-gradient-to-br from-primary to-primary-container text-white rounded-lg shadow-md`
- Secondary: `bg-surface-container-highest text-on-surface rounded-lg`

### Glass Panels
```css
background: rgba(255, 255, 255, 0.7);
backdrop-filter: blur(24px);
```

### Tables
- Header: `bg-surface-container-low` with `text-[10px] font-extrabold uppercase tracking-widest`
- Rows: hover `bg-blue-50/30` or `bg-slate-50`
- No row borders (use `divide-y divide-surface-container-low`)

## Nav Items (Sidebar)

| Label | Icon | Route |
|---|---|---|
| Overview | `dashboard` | `/` |
| Topology | `hub` | `/topology` |
| Devices | `router` | `/devices` |
| Health | `monitor_heart` | `/approvals` |
| AI Insights | `psychology` | `/insights` |

Active state: `text-blue-700 bg-blue-50/50 rounded-lg`
