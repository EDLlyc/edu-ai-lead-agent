"""Reversible offline image build after final source gate; no service changes."""
import hashlib,json,subprocess
from pathlib import Path
STAGE=Path(__file__).resolve().parent
BASE='sha256:24e967081b2e9b303a1f295e7e99eacd24ed96304d5cbb5bd3645270fe159249'
ALIAS='offline.local/edu-ai/edu-ai-lead-agent-backend:admin-history-base-24e96708'
COMMIT=(STAGE/'source-commit.txt').read_text().strip()
TAG='offline.local/edu-ai/edu-ai-lead-agent-backend:admin-history-'+COMMIT[:7]

def run(args,label):
 r=subprocess.run(args,capture_output=True,text=True,timeout=240)
 p=STAGE/(label+'.log');p.write_text(r.stdout+'\n'+r.stderr);p.chmod(0o600)
 if r.returncode:raise RuntimeError(label+' failed; see private staging log')
 return r.stdout.strip()
actual=run(['docker','inspect','--format','{{.Image}}','edu-ai-lead-agent-acquisition-api-1'],'current-image')
assert actual==BASE,'Production base changed'
run(['docker','tag',BASE,ALIAS],'base-tag')
run(['docker','build','--pull=false','--network=none','-t',TAG,str(STAGE/'context')],'image-build')
image=run(['docker','image','inspect','--format','{{.Id}}',TAG],'candidate-id')
smoke=run(['docker','run','--rm','--network','none','--entrypoint','python','--mount','type=bind,src='+str(STAGE/'smoke.py')+',dst=/app/.admin-history-smoke.py,readonly',image,'/app/.admin-history-smoke.py'],'offline-smoke')
assert 'offline smoke passed' in smoke
assets=json.loads((STAGE/'frontend-sha256.json').read_text())
for name,expected in assets.items():assert hashlib.sha256((STAGE/'dist-admin'/name).read_bytes()).hexdigest()==expected
value={'image':image,'source_commit':COMMIT,'base_image':BASE,'frontend':assets,'offline_smoke':smoke}
(STAGE/'candidate.json').write_text(json.dumps(value,indent=2)+'\n');(STAGE/'candidate.json').chmod(0o600)
# Verify the exact digest notation used by the existing compose image pin resolves locally.
resolved=run(['docker','image','inspect','--format','{{.Id}}','offline.local/edu-ai/edu-ai-lead-agent-backend@'+image],'digest-reference')
assert resolved==image
print(json.dumps(value,indent=2))
