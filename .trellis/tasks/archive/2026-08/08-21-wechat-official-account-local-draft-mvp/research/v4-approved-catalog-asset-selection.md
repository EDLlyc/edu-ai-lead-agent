# V4 approved-catalog asset selection

Date: 2026-08-25

## Boundary

- Input authority: the existing manifest-approved 41-item brand visual catalog.
- Read path: `LocalOfficialAccountCatalogMediaProvider` only.
- Selection mode: deterministic local public-ref and semantic-tag match; no embedding, image-generation, network,
  WeChat, WeCom or publish call.
- Export boundary: public ref, catalog version, semantic tags, source-master checksum and publication checksum only.
  Private path, raw asset ID, filename, vectors, prompts and source-master bytes are excluded.
- Historical refs `33586a916bbbfbf1`, `5c2a29bbec16ca4f` and `09c8fd9470cb5502` are excluded from the new pair.

## Selected pair

### Parent-question cutaway

- Public ref: `1bb84f2abb140b8f`
- Reader label: 小赛和赛先生思考
- Tags used: `discuss`, `editorial`, `education`, `reading`, `science`, `think`, `thinking`
- Publication profile: metadata-free JPEG, 614x614, 22,620 bytes
- Publication SHA-256: `042366d47e654a49f3bac1f710d55becec739c27ed63d8026a6ae3fdca96ea9d`
- Binding: section index 1, after the three parent-question paragraphs and before the interpretation boundary.

### AI/child-boundary cutaway

- Public ref: `bab27fe77a8edff4`
- Reader label: 小赛探测
- Tags used: `ai`, `discover`, `experiment`, `explore`, `observe`, `robotics`, `robotics_lab`, `science`
- Publication profile: metadata-free JPEG, 1536x1536, 154,557 bytes
- Publication SHA-256: `266f21c5f058ef4e321fd9c1ee0e2770d86633fccd039f9df51a87e310f7db47`
- Binding: section index 3, after the structured AI/child responsibility list and before its closing rule.

## Presentation decision

Both derivatives are square IP cutaways rather than 3:2 narrative scenes. The renderer must use a contained
composition on an intentional colored field; it must not force the images through the existing 3:2 cover crop.
This creates a clear editorial distinction between the three inherited generated scenes and the two approved
brand-library annotations while keeping all five images attached to an exact Article Package block.
