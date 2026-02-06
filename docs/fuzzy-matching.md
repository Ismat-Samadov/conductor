# Fuzzy Matching & Azerbaijani Transliteration

Conductor handles Azerbaijani text input that may be typed with or without special characters. The matching pipeline resolves user input like `"genclik metrosu"` to the actual stop name `"Gənclik m/st"`.

---

## Matching Pipeline

The `StopMatcher.match()` method tries three strategies in order:

```
User Input: "genclik metrosu"
       |
       v
  [1. Alias Lookup] ── check exact match + transliteration variants
       |  found? → return stops
       v
  [2. Direct Search] ── CONTAINS query on nameNormalized
       |  found? → return stops
       v
  [3. Variant Search] ── generate all transliteration variants, try each
       |  found? → return stops
       v
  Empty result (stop not found)
```

---

## 1. Alias Dictionary (`conductor/matching/aliases.py`)

Maps common user terms to actual stop name substrings. Covers:

- **Azerbaijani metro stations** with proper characters: `"gənclik metrosu"` → `["gənclik m/st"]`
- **ASCII variants** (typed without special chars): `"genclik metrosu"` → `["gənclik m/st"]`
- **Short forms**: `"genclik"` → `["gənclik m/st"]`

### Covered Metro Stations

| User Input | Resolves To |
|---|---|
| genclik, genclik metrosu, gənclik | Gənclik m/st |
| 28 may, 28 may metrosu | 28 May m/st |
| koroglu, koroğlu metrosu | Koroğlu m/st |
| narimanov, nərimanov metro | Nərimanov m/st |
| sahil, sahil metrosu | Sahil m/st |
| nizami, nizami metro | Nizami m/st |
| icherisheher, içərişəhər | İçərişəhər m/st |
| elmler akademiyasi | Elmlər Akademiyası m/st |
| and 15+ more... | |

The alias lookup also tries transliteration variants of the input, so `"genclik metrosu"` generates `"gənclik metrosu"` which matches the Azerbaijani alias.

---

## 2. Transliteration (`conductor/matching/transliterate.py`)

### Character Maps

**Azerbaijani → ASCII:**

| Azerbaijani | ASCII |
|---|---|
| ə | e |
| ş | s |
| ç | c |
| ö | o |
| ü | u |
| ğ | g |
| ı | i |

**Multi-character ASCII → Azerbaijani:**

| ASCII | Azerbaijani |
|---|---|
| sh | ş |
| ch | ç |
| gh | ğ |
| oe | ö |
| ue | ü |

### Variant Generation

`generate_variants("genclik")` produces:

```
["genclik", "gənclik", "ğenclik", "genclık"]
```

Each variant tries a different character substitution:
1. Original input
2. All `e` → `ə`
3. All `g` → `ğ`
4. All `i` → `ı`
5. Multi-char expansions (`sh` → `ş`, etc.)
6. ASCII-ified version (for inputs with Azerbaijani chars)

---

## 3. Neo4j Search

Both alias results and variants are searched against Neo4j using:

```cypher
MATCH (s:Stop)
WHERE s.nameNormalized CONTAINS $name
RETURN s.id, s.name
ORDER BY s.isTransportHub DESC, s.name
LIMIT 5
```

The `CONTAINS` operator enables partial matching — searching for `"gənclik m/st"` matches stops named `"Gənclik m/st "`, `"Gənclik m/st (digər)"`, etc.

---

## Location-Aware Matching

When the user has a known location, `StopMatcher.match_near()` fetches up to 20 candidates and sorts them by distance from the user. This ensures the closest matching stop is preferred when multiple stops share the same name.

---

## Examples

| User Input | Alias Match | Variant Match | Result |
|---|---|---|---|
| `genclik metrosu` | `"genclik metrosu"` → `gənclik m/st` | - | Gənclik m/st |
| `Gənclik m/st` | `"gənclik"` → `gənclik m/st` | - | Gənclik m/st |
| `28 may` | `"28 may"` → `28 may m/st` | - | 28 May m/st |
| `koroglu` | `"koroglu"` → `koroğlu m/st` | - | Koroğlu m/st |
| `badamdar` | no alias | direct search hits `nameNormalized` | Badamdar qəs. |
| `F.Xoyski` | no alias | direct search | F.Xoyski küç. stops |
