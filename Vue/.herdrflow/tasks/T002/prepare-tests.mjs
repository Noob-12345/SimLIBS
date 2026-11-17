import fs from 'node:fs'
const dir='.herdrflow/tasks/T002'
const old=fs.readFileSync('.herdrflow/tasks/T001/cdp-check.mjs','utf8')
const nl=String.fromCharCode(10)
const prefix=old.slice(0,old.indexOf(nl+'try{'+nl))
const header=prefix.replaceAll('T001','T002').replaceAll('t001','t002').replaceAll('8e243d04-0640-4f35-841b-efb28c7198b6','15198f82-1795-4b8e-8426-e82418e3d97c').replaceAll('window.__frames','window.__t002Frames')
const body=fs.readFileSync(dir+'/behavior-body.mjs','utf8')
const footer=old.slice(old.indexOf(nl+'finally{'+nl)).replaceAll('T001','T002').replaceAll('t001','t002')
fs.writeFileSync(dir+'/cdp-check.mjs',header+body+footer)
const rows=['wave,signal,other,alternate']
for(let i=0;i<120;i++){const x=240+i,signal=i===40?8000:i===100?200:-90;rows.push([x,signal,i===40?2000:i===100?50:-25,x+100].join(','))}
fs.writeFileSync(dir+'/ui-test.csv',rows.join(nl)+nl)
fs.writeFileSync(dir+'/duplicate-ui-test.csv',['wave,signal','400,-3','400,-2','401,4'].join(String.fromCharCode(10)))
fs.writeFileSync(dir+'/invalid-ui-test.csv','wave,signal'+String.fromCharCode(10)+'bad,1'+String.fromCharCode(10)+'bad,2')
