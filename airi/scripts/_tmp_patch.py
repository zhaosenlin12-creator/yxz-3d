import re, pathlib
for name in ["scripts/probe_yxz_candidate_parts.mjs","scripts/probe_yxz_candidate_visemes.mjs"]:
    p=pathlib.Path(name)
    s=p.read_text(encoding="utf-8")
    old="!url.pathname.endsWith('/yxz.vrm')"
    if old in s:
        s=s.replace(old,"!url.pathname.endsWith('.vrm')")
        p.write_text(s,encoding="utf-8")
        print("patched",name)
    else:
        print("no match in",name, [l for l in s.splitlines() if ".vrm" in l][:5])
