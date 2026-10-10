# UDF 2.50 preflight — Reserve VDS follow-up

Scope: Full HD BD25/BD50 only. This review applies to draft PR #16.

## Verified implementation gap

The current ISO inspector checks the primary or backup **Anchor Volume Descriptor Pointer** (AVDP), but reads only the **Main Volume Descriptor Sequence** (Main VDS) described by that anchor. It does not attempt the separate **Reserve Volume Descriptor Sequence** (Reserve VDS) extent. Consequently, an ISO with a damaged Main VDS and intact Reserve VDS is rejected even though the backup metadata may be usable.

The backup AVDP and the Reserve VDS are different recovery mechanisms. Do not claim both are covered by a backup-anchor test.

## Proposed regression tests

1. Main VDS valid: retain existing success path and UDF revision check.
2. Main LVD CRC corrupt; Reserve LVD valid: inspect Reserve VDS, return metadata-only success with an explicit fallback warning.
3. Main extent out of bounds; Reserve extent valid: recover via Reserve VDS.
4. Main and Reserve extents invalid: reject the ISO.
5. Main and Reserve LVDs both invalid: reject the ISO.
6. Reserve VDS revision 0x0260: reject as not UDF 2.50.
7. Reserve VDS descriptor tag checksum/location/CRC invalid: reject rather than accept unchecked metadata.

## Release boundary

Synthetic fixtures and green CI cannot establish a mountable filesystem, correct BDMV directory tree, valid Blu-ray menus, or standalone player compatibility. Validate a real generated ISO with a UDF-aware mount/inspection tool, burn a BD-RE using ASUS BW-16D1HT, verify readback, and test navigation on a household player before making those claims.

Do not merge this note as evidence that Reserve VDS fallback is implemented; it documents a pending improvement.
