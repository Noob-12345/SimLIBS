/* Shared controls, with separate values and event state for each editor. */
function controlsPayload(scope){
  const id=CONTROL_IDS[scope],mode=scope==='single'?state.mode:$('#batchMode').value;
  const random=scope==='batch'&&$('#batchGeneration').value==='random';
  const header=scope==='batch'&&$('#batchGeneration').value==='template'&&state.templateText?state.templateText.split(/\r?\n/)[0]:'';
  const te=header.includes('Te[eV]')?1:random&&$('#randomTe').checked?numericInput('batchTeA','Te下界'):numericInput(id.te,'Te');
  const ne=header.includes('Ne[cm^-3]')?1e17:random&&$('#randomNe').checked?numericInput('batchNeA','实际Ne下界'):numericInput(id.ne,'实际Ne');
  const low=numericInput(id.low,'波长下界'),up=numericInput(id.up,'波长上界');if(low>=up)throw new Error('波长上界须大于下界');
  const broaden=mode!=='local'||$('#'+id.broad).checked;
  return {mode,mode_version:2,te,ne,resolution:numericInput(id.r,'R',true),low_w:low,up_w:up,max_ion_charge:Number($('#'+id.charge).value),
    headless:$('#'+id.headless).checked,intensity_scale:mode==='local'?'photon':$('#'+id.flux).value,
    broadening:mode==='server'?'nist':'local',local_broadening_enabled:broaden,broaden_convention:mode==='local'?'physics':mode==='client'?$('#'+id.convention).value:'nist',
    broaden_grid_step:mode==='server'?.005:numericInput(id.grid,'采样 / 合成网格步长'),
    broaden_center_decimals:mode==='client'&&$('#'+id.center).value.trim()!==''?numericInput(id.center,'线中心舍入',true,0):null,
    broaden_min_rel_int:mode==='client'?numericInput(id.threshold,'选线阈值',false,0):0,
    resample:$('#'+id.resample).checked,resample_step:$('#'+id.resample).checked?numericInput(id.step,'目标网格步长'):.01,
    local_gaussian_nm:mode==='local'&&broaden?numericInput(id.gaussian,'高斯FWHM',false,0):0,
    local_lorentz_nm:mode==='local'&&broaden?numericInput(id.lorentz,'洛伦兹FWHM',false,0):0,
    local_temperature_mode:mode==='local'?$('#'+id.temperatureMode).value:'manual',
    local_temperature_K:mode==='local'&&broaden&&$('#'+id.temperatureMode).value==='manual'?numericInput(id.temperature,'重粒子温度',false,0):0};
}
function updateControlVisibility(scope){
  const id=CONTROL_IDS[scope],mode=scope==='single'?state.mode:$('#batchMode').value,broaden=$('#'+id.broad).checked;
  $('#'+id.mode).value=mode;$$('#'+id.seg+' button').forEach(b=>b.classList.toggle('on',b.dataset.v===mode));
  $('#'+id.nist).hidden=mode==='local';$('#'+id.localFlux).hidden=mode!=='local';$('#'+id.broadControl).hidden=mode!=='local';
  $('#'+id.headlessControl).hidden=mode!=='server';$('#'+id.params).hidden=mode==='server';
  $('#'+id.widths).hidden=mode!=='local'||!broaden;$('#'+id.thermal).hidden=mode!=='local'||!broaden;
  $('#'+id.params+' .client-parameters').hidden=mode!=='client';$('#'+id.gridControl).hidden=mode==='server';
  $('#'+id.path).textContent=mode==='local'?(broaden?'用户线库 · 本地展宽':'用户线库 · 未展宽线谱'):mode==='client'?'NIST线表 · Python展宽':'NIST数据 · 官方JS重算';
  $('#'+id.resampleControl).hidden=!$('#'+id.resample).checked;
  const linked=$('#'+id.temperatureMode).value==='linked';$('#'+id.temperatureInput).hidden=linked;$('#'+id.linkedHint).hidden=!linked;
  const te=Number($('#'+id.te).value),kelvin=te*1.602176634e-19/1.380649e-23;
  $('#'+id.linkedHint).textContent=scope==='batch'&&$('#batchGeneration').value==='random'&&$('#randomTe').checked?'Tₕ 随实际随机 Te':Number.isFinite(kelvin)&&kelvin>0?'Tₕ = '+kelvin.toExponential(4)+' K':'';
}
function updateOptionalControls(){updateControlVisibility('single');updateControlVisibility('batch');}
function updateModePath(){state.broadening=state.mode==='server'?'nist':'local';updateControlVisibility('single');updateLocalNotices();}
function updateBatchMode(){updateControlVisibility('batch');updateLocalNotices();}
function bindControlSliders(scope){
  const id=CONTROL_IDS[scope];
  const refresh=()=>{for(const key of ['te','ne','r']){const n=Number($('#'+id[key]).value||NaN),slider=$('#'+id[key+'Slider']),value=key==='ne'?Math.log10(n):n;
    if(Number.isFinite(value)&&n>0){slider.min=Math.min(Number(slider.min),value);slider.max=Math.max(Number(slider.max),value);slider.value=value;fillSlider(slider);}
    $('#'+id[key+'Val']).textContent=Number.isFinite(n)?(key==='ne'?numberLabel(n)+' cm⁻³':key==='te'?numberLabel(n)+' eV':n):'无效';}
    updateOptionalControls();if(scope==='single'){updateParamLabels();schedulePreview();}else updateBatchSum();};
  for(const key of ['te','ne','r']){
    $('#'+id[key+'Slider']).addEventListener('input',()=>{const n=Number($('#'+id[key+'Slider']).value);$('#'+id[key]).value=key==='ne'?formatDensity(Number((10**n).toPrecision(15))):n;refresh();});
    $('#'+id[key]).addEventListener('input',refresh);
  }
  $('#'+id.ne).addEventListener('blur',()=>{const n=Number($('#'+id.ne).value);if(Number.isFinite(n)&&n>0)$('#'+id.ne).value=formatDensity(n);});
  refresh();
}
function generationPayload(){
  const kind=$('#batchGeneration').value,random=kind==='random';
  const scalar=(enabledId,minId,maxId,label)=>{const enabled=random&&$('#'+enabledId).checked;return enabled?{enabled,min:numericInput(minId,label+'下界'),max:numericInput(maxId,label+'上界')}:{enabled:false};};
  const concentrations=state.batchComp.map(c=>{const el=canonicalElement(c.el);if(!el)throw new Error('无效元素：'+c.el);const enabled=random&&!!c.randomEnabled;
    const value=percentageValue(c.pct);if(!enabled&&(!Number.isFinite(value)||value<0||value>100))throw new Error(el+'固定浓度须在0–100%');
    const rule={el,enabled};if(enabled){const lo=percentageValue(c.min),hi=percentageValue(c.max);if(!Number.isFinite(lo)||!Number.isFinite(hi)||lo<0||hi>100||lo>hi)throw new Error(el+'浓度边界非法');rule.min=lo;rule.max=hi;}else rule.fixed=value;return rule;});
  if(new Set(concentrations.map(c=>c.el)).size!==concentrations.length)throw new Error('元素重复');
  const lo=concentrations.reduce((s,c)=>s+(c.enabled?c.min:c.fixed),0),hi=concentrations.reduce((s,c)=>s+(c.enabled?c.max:c.fixed),0);
  if(lo>100+1e-9||hi<100-1e-9)throw new Error('浓度边界不能容纳100%：请检查固定值和上下界');
  if($('#batchMode').value==='local')for(const c of concentrations){const minimum=c.enabled?c.min:c.fixed;const possible=c.enabled?Math.min(c.max,100-(lo-minimum)):c.fixed;if(possible>0&&!state.localSymbols.includes(c.el))throw new Error(c.el+'缺少可用本地谱线；不会向NIST回退');}
  const rule={kind,te:scalar('randomTe','batchTeA','batchTeB','Te'),ne:scalar('randomNe','batchNeA','batchNeB','实际Ne'),concentrations};
  for(const r of [rule.te,rule.ne])if(r.enabled&&r.min>r.max)throw new Error('随机参数下界不能大于上界');
  return rule;
}
function updateBatchSum(){
  try{if($('#batchGeneration').value==='template'){ $('#batchSumRow').hidden=true;return; }$('#batchSumRow').hidden=false;generationPayload();$('#batchSumVal').textContent='100% ✓';$('#batchSumRow').className='sum-row ok';}
  catch(e){$('#batchSumVal').textContent=e.message;$('#batchSumRow').className='sum-row bad';}
  updateLocalNotices();
}
function percentageValue(value){return typeof value==='string'&&!value.trim()?NaN:Number(value);}
function syncBatchPercentages(){
  const random=$('#batchGeneration').value==='random';
  $$('#batchCompRows .batch-composition-row').forEach((row,i)=>{
    const c=state.batchComp[i],disabled=random&&!!c.randomEnabled;
    const pct=row.querySelector('.batch-pct'),slider=row.querySelector('.batch-pct-slider'),n=percentageValue(c.pct);
    pct.disabled=slider.disabled=disabled;pct.setAttribute('aria-invalid',String(!disabled&&(!Number.isFinite(n)||n<0||n>100)));
    if(Number.isFinite(n)&&n>=0&&n<=100)slider.value=n;
    fillSlider(slider);row.querySelector('.batch-random-switch').hidden=!random;
    row.querySelector('.concentration-bounds').hidden=!disabled;
  });
}
function updateGeneration(){
  const kind=$('#batchGeneration').value;$$('#batchGenerationSeg button').forEach(b=>b.classList.toggle('on',b.dataset.v===kind));
  $('#batchFixedControls').hidden=kind!=='fixed';$('#batchRandomControls').hidden=kind!=='random';$('#batchTemplateControls').hidden=kind!=='template';
  // Move the one editor, preserving DOM identity, focused input drafts and listeners.
  const editor=$('#batchCompositionEditor'),target=kind==='random'?$('#batchRandomComposition'):kind==='fixed'?$('#batchFixedControls'):null;
  if(target&&editor.parentNode!==target)target.appendChild(editor);
  $('#randomTeBounds').hidden=kind!=='random'||!$('#randomTe').checked;$('#randomNeBounds').hidden=kind!=='random'||!$('#randomNe').checked;
  for(const [key,randomId] of [['te','randomTe'],['ne','randomNe']])for(const id of [CONTROL_IDS.batch[key],CONTROL_IDS.batch[key+'Slider']])$('#'+id).disabled=kind==='random'&&$('#'+randomId).checked;
  syncBatchPercentages();
  updateBatchSum();updateOptionalControls();
}
function renderBatchComposition(){
  const box=$('#batchCompRows');box.replaceChildren();
  state.batchComp.forEach((c,i)=>{
    if(c.min===undefined)c.min='0';if(c.max===undefined)c.max='100';
    const entry=document.createElement('div');entry.className='batch-composition-row';entry.id='batchCompositionRow'+i;
    const row=document.createElement('div');row.className='comp-row';const picker=document.createElement('div');picker.className='element-picker';
    const el=document.createElement('input');el.className='batch-el';el.value=c.el;el.maxLength=4;el.autocomplete='off';el.spellcheck=false;
    el.setAttribute('role','combobox');el.setAttribute('aria-autocomplete','list');el.setAttribute('aria-expanded','false');el.setAttribute('aria-label','元素 '+(i+1));el.setAttribute('aria-controls','batchOptions'+i);
    const list=document.createElement('div');list.className='element-options';list.hidden=true;list.id='batchOptions'+i;list.setAttribute('role','listbox');picker.append(el,list);
    bindElementPicker(el,list,c,i,state.batchComp,()=>$('#batchMode').value,()=>{updateBatchSum();});
    const pct=document.createElement('input');pct.type='text';pct.inputMode='decimal';pct.className='batch-pct';pct.value=c.pct;pct.setAttribute('aria-label','元素 '+(i+1)+' 固定占比 [%]');
    const valueControl=document.createElement('div');valueControl.className='batch-pct-control';const unit=document.createElement('span');unit.textContent='%';valueControl.append(pct,unit);
    const slider=document.createElement('input');slider.type='range';slider.min=0;slider.max=100;slider.step='any';slider.className='batch-pct-slider';slider.setAttribute('aria-label','元素 '+(i+1)+' 固定占比滑块');
    const edited=(commit=false)=>{c.pct=pct.value;if($('#batchGeneration').value==='fixed')balanceBatch(i,commit);syncBatchPercentages();updateBatchSum();};
    pct.addEventListener('input',()=>edited());pct.addEventListener('blur',()=>edited(true));
    slider.addEventListener('input',()=>{pct.value=slider.value;edited(true);});
    const remove=document.createElement('button');remove.type='button';remove.className='comp-del';remove.textContent='✕';remove.setAttribute('aria-label','删除元素 '+(i+1));remove.addEventListener('click',()=>{state.batchComp.splice(i,1);renderBatchComposition();});
    row.append(picker,valueControl,remove);
    const label=document.createElement('label');label.className='switch batch-random-switch';const toggle=document.createElement('input');toggle.type='checkbox';toggle.checked=!!c.randomEnabled;toggle.id='randomConcentration'+i;toggle.setAttribute('aria-label','元素 '+(i+1)+' 浓度随机');
    const track=document.createElement('span');track.className='track';const caption=document.createElement('span');caption.textContent='随机';label.append(toggle,track,caption);
    const bounds=document.createElement('div');bounds.className='row2 concentration-bounds';
    for(const key of ['min','max']){const field=document.createElement('div'),input=document.createElement('input'),heading=document.createElement('label');input.type='text';input.inputMode='decimal';input.value=c[key];input.id='concentration'+(key==='min'?'Min':'Max')+i;heading.className='f';heading.htmlFor=input.id;heading.textContent=(key==='min'?'下界':'上界')+' [%]';input.addEventListener('input',()=>{c[key]=input.value;updateBatchSum();});field.append(heading,input);bounds.append(field);}
    toggle.addEventListener('change',()=>{c.randomEnabled=toggle.checked;syncBatchPercentages();updateBatchSum();});
    entry.append(row,slider,label,bounds);box.append(entry);
  });
  if($('#batchGeneration').value==='fixed')balanceBatch();updateGeneration();
}
function balanceBatch(edited=-1,commit=true){
  const values=state.batchComp.map(c=>percentageValue(c.pct));if(!values.length||values.some(v=>!Number.isFinite(v)||v<0))return;
  let clipped=-1;
  if(values.length===1)values[0]=100;
  else{const last=values.length-1,prior=values.slice(0,last).reduce((a,b)=>a+b,0);if(prior>100){const others=prior-values[edited];if(edited>=0&&edited<last&&others<=100){values[edited]=100-others;clipped=edited;}else return;}values[last]=100-values.slice(0,last).reduce((a,b)=>a+b,0);}
  state.batchComp.forEach((c,i)=>{if(i===values.length-1||i===clipped)c.pct=values[i];const input=$('#batchCompRows').querySelectorAll('.batch-pct')[i];if(input&&(i!==edited||commit))input.value=c.pct;});
}
