"""Editing Steam's GLOBAL config.vdf is the riskiest thing Loadout does — a corrupt file costs
the user their whole Steam configuration. Prove the edits are surgical and refuse to be wrong."""
import os, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import steam_compat as C

REAL = '''"InstallConfigStore"
{
\t"Software"
\t{
\t\t"Valve"
\t\t{
\t\t\t"Steam"
\t\t\t{
\t\t\t\t"CompatToolMapping"
\t\t\t\t{
\t\t\t\t\t"362890"
\t\t\t\t\t{
\t\t\t\t\t\t"name"\t\t"proton_experimental"
\t\t\t\t\t\t"config"\t\t""
\t\t\t\t\t\t"priority"\t\t"250"
\t\t\t\t\t}
\t\t\t\t}
\t\t\t}
\t\t}
\t}
}
'''
NO_SECTION = REAL.replace('''\t\t\t\t"CompatToolMapping"
\t\t\t\t{
\t\t\t\t\t"362890"
\t\t\t\t\t{
\t\t\t\t\t\t"name"\t\t"proton_experimental"
\t\t\t\t\t\t"config"\t\t""
\t\t\t\t\t\t"priority"\t\t"250"
\t\t\t\t\t}
\t\t\t\t}
''', '')

fails = []
def mkhome(txt):
    h = tempfile.mkdtemp()
    d = os.path.join(h, ".local/share/Steam/config"); os.makedirs(d)
    open(os.path.join(d, "config.vdf"), "w").write(txt)
    return h

# 1. add a mapping for a new appid, leaving the existing one alone
h = mkhome(REAL)
assert C.set_tool(3359702471, "proton_10", home=h)
txt = open(C.config_path(h)).read()
print("  added: 3359702471 -> %r   existing 362890 -> %r"
      % (C.get_tool(3359702471, home=h), C.get_tool(362890, home=h)))
if C.get_tool(3359702471, home=h) != "proton_10": fails.append("new mapping not written")
if C.get_tool(362890, home=h) != "proton_experimental": fails.append("clobbered an existing mapping")
if txt.count("{") != txt.count("}"): fails.append("unbalanced braces after insert")
print("  braces balanced: %s   backup written: %s"
      % (txt.count("{") == txt.count("}"), os.path.exists(C.config_path(h) + ".loadout-bak")))

# 2. updating an existing appid changes only its name
assert C.set_tool(362890, "proton_9", home=h)
print("  updated 362890 -> %r (3359702471 still %r)"
      % (C.get_tool(362890, home=h), C.get_tool(3359702471, home=h)))
if C.get_tool(362890, home=h) != "proton_9": fails.append("update did not take")
if C.get_tool(3359702471, home=h) != "proton_10": fails.append("update disturbed the other entry")
t2 = open(C.config_path(h)).read()
if t2.count("{") != t2.count("}"): fails.append("unbalanced after update")

# 3. a no-op write reports no change (so we never touch the file needlessly)
print("  rewriting the same value changed the file: %s (expect False)"
      % C.set_tool(362890, "proton_9", home=h))
if C.set_tool(362890, "proton_9", home=h): fails.append("rewrote an unchanged value")

# 4. a config with no CompatToolMapping section gets one created in the right place
h2 = mkhome(NO_SECTION)
assert C.set_tool(999, "proton_10", home=h2)
t3 = open(C.config_path(h2)).read()
print("  created section from scratch: %r  balanced=%s"
      % (C.get_tool(999, home=h2), t3.count("{") == t3.count("}")))
if C.get_tool(999, home=h2) != "proton_10": fails.append("could not create the section")
if t3.count("{") != t3.count("}"): fails.append("unbalanced after creating the section")
if "InstallConfigStore" not in t3: fails.append("mangled the file")

# 5. no Steam install -> no crash, no write
print("  no steam install: %s (expect False)" % C.set_tool(1, "proton_10", home=tempfile.mkdtemp()))

# 6. version picking matches what Steam calls its builds
h3 = tempfile.mkdtemp(); cd = os.path.join(h3, ".local/share/Steam/steamapps/common"); os.makedirs(cd)
for n in ("Proton - Experimental", "Proton 10.0", "Proton 9.0 (Beta)",
          "Proton EasyAntiCheat Runtime", "Proton BattlEye Runtime"):
    os.makedirs(os.path.join(cd, n))
got = C.newest_proton(home=h3)
print("  deck1's actual Proton set -> %r (expect 'proton_10')" % got)
if got != "proton_10": fails.append("picked %r instead of proton_10" % got)
h4 = tempfile.mkdtemp(); os.makedirs(os.path.join(h4, ".local/share/Steam/steamapps/common/Proton - Experimental"))
print("  only Experimental installed -> %r" % C.newest_proton(home=h4))
if C.newest_proton(home=h4) != "proton_experimental": fails.append("no fallback to experimental")

print("FAIL: " + "; ".join(fails) if fails else "PASS")
sys.exit(1 if fails else 0)
