# Full HD Blu-ray BDMV preflight

Run: python -m bdmv_preflight PATH_TO_DISC_FOLDER --profile BD25

Checks: supported INDX/MOBJ/MPLS/CLPI version headers, five-digit BDMV filenames, matching CLIPINF/STREAM identifiers, sampled 192-byte M2TS sync bytes and BD25/BD50 size. Exit 0: limited structural checks passed. Exit 2: checks failed. Output is JSON. This is NOT UDF 2.50 validation, a menu test, or evidence of hardware player compatibility. Only BD25 and BD50 are in scope. UHD/4K/BDXL deferred.
