import fs from 'node:fs'
import crypto from 'node:crypto'
import {execFileSync} from 'node:child_process'
const root='D:/LIBS/SimLIBS/Vue',dir='.herdrflow/tasks/T004/'
const baseline=JSON.parse(fs.readFileSync(dir+'baseline.json','utf8').replace(/^\uFEFF/,''))
const git=(...args)=>execFileSync('git',args,{cwd:root,encoding:'utf8',windowsHide:true})
const hash=file=>{const data=fs.readFileSync(file);return{file,bytes:data.length,sha256:crypto.createHash('sha256').update(data).digest('hex')}}
const allowed=['backend/simlibs_ui/spectrum_nist.py','backend/simlibs_ui/spectrum_browser.py','backend/tests/test_spectrum_nist.py','src/lib/spectrumBrowser.ts','src/components/BrowserReferencePanel.vue']
const added=['backend/simlibs_ui/spectrum_nist.py','backend/tests/test_spectrum_nist.py']
let diff=git('diff','--relative','--no-ext-diff','--',...allowed)
for(const file of added){const content=fs.readFileSync(file,'utf8').replace(/\r\n/g,'\n').replace(/\n$/,'');const lines=content.split('\n');diff+='diff --git a/'+file+' b/'+file+'\nnew file mode 100644\n--- /dev/null\n+++ b/'+file+'\n@@ -0,0 +1,'+lines.length+' @@\n'+lines.map(line=>'+'+line).join('\n')+'\n'}
fs.writeFileSync(dir+'final-source.diff',diff)
const protectedFiles=baseline.protected.map(item=>({...hash(item.file),baselineSha256:item.sha256,unchanged:hash(item.file).sha256===item.sha256}))
const changed=git('diff','--relative','--name-only').trim().split(/\r?\n/).filter(Boolean)
const unexpected=changed.filter(file=>!allowed.includes(file)&&!baseline.existingDirty.includes(file))
git('diff','--relative','--check')
const artifactFiles=['src-tauri/target/release/simlibs-vue.exe','src-tauri/target/release/bundle/nsis/SimLIBS_0.1.0_x64-setup.exe','dist-desktop/SimLIBS.exe','dist-desktop/SimLIBS-Setup.exe']
const evidence=['implementation.md','final-source.diff','unit-tests.log','parser-check.log','live-nist.json','browser-check.json','cleanup-check.json','build.log','desktop-build.log','cdp-check.mjs','harness.mjs','harness.html','cdp-server.py','capture-html.py','inspect-parser.py','live-fetch.py','freeze.mjs'].map(file=>dir+file)
const report={taskId:'T004',dispatchId:'229c687f-8bda-4b35-bea4-2e7841ace916',revision:1,at:new Date().toISOString(),head:git('rev-parse','HEAD').trim(),frozen:true,sources:allowed.map(hash),newUntrackedSources:added,artifacts:artifactFiles.map(hash),existingDirty:baseline.existingDirty,relativeChanged:changed,unexpectedPaths:unexpected,diffCheckExitCode:0,protectedCount:protectedFiles.length,protectedMismatches:protectedFiles.filter(item=>!item.unchanged),protectedFiles,unitTests:{passed:7,exitCode:0},browser:{realQueryPassed:true,pendingReview:['source coexistence and closed-II refresh','failed/cancel/clear stale-response behavior','actual dashed-line tooltip hit'],cleanupEvidence:'cleanup-check.json'},desktopBuildExitCode:0,rootCollected:false,rootBoundary:'dist-desktop is the pre-existing version, not the T004 release; collect not executed',evidence:evidence.map(hash)}
fs.writeFileSync(dir+'final-files.json',JSON.stringify(report,null,2)+'\n')
for(const item of [...report.sources,...report.artifacts,...report.evidence])if(hash(item.file).sha256!==item.sha256)throw Error('Final hash mismatch '+item.file)
if(unexpected.length||report.protectedMismatches.length)throw Error('Scope/protected mismatch')
console.log(JSON.stringify({taskId:report.taskId,dispatchId:report.dispatchId,revision:report.revision,sources:report.sources,releaseArtifacts:report.artifacts.slice(0,2),protectedCount:report.protectedCount,protectedMismatches:report.protectedMismatches.length,unexpectedPaths:unexpected,diffCheckExitCode:0,rootCollected:false},null,2))
