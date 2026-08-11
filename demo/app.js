const state={records:[],index:0,timer:null};
const colors={Healthy:'#38d996',Warning:'#f5c84c',Degraded:'#ff8b42',Critical:'#ff5364',Unknown:'#8fa7b5'};
const names={adcs:'ADCS',cdh:'C&DH',command_control:'Command & control'};
const $=id=>document.getElementById(id);
const safe=v=>v===null||v===undefined?'—':v;

async function load(){
  try{
    const response=await fetch('../data/outputs/health/health_predictions.json');
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload=await response.json();
    state.records=payload.report;
    buildScenarios(); render(0);
  }catch(error){
    $('timestamp').textContent='Unable to load data. Start with: python demo/start_demo.py';
    console.error(error);
  }
}

function buildScenarios(){
  ['Healthy','Warning','Degraded','Critical'].forEach(status=>{
    const button=document.createElement('button'); button.textContent=status;
    button.onclick=()=>{let i=state.records.findIndex(r=>r.overall_health.status===status);if(i<0)i=state.records.findIndex(r=>r.prediction===status);if(i>=0)render(i)};
    $('scenarios').appendChild(button);
  });
}

function render(index){
  state.index=(index+state.records.length)%state.records.length;
  const r=state.records[state.index], overall=r.overall_health, status=overall.status;
  $('satellite').textContent=r.satellite_id;
  $('timestamp').textContent=new Date(r.timestamp).toLocaleString();
  $('status').textContent=status; $('status').className=status;
  $('status-dot').style.background=colors[status]; $('status-dot').style.boxShadow=`0 0 16px ${colors[status]}`;
  renderOverallExplanation(r);
  const confidence=Math.round((r.predicted_probability||0)*100);
  $('confidence').textContent=`${confidence}%`; $('confidence-bar').style.width=`${confidence}%`;
  $('assurance').textContent=r.model_assurance.accepted?'Accepted':'Abstained';
  $('assurance').className=r.model_assurance.accepted?'Healthy':'Critical';
  $('assurance-note').textContent=r.model_assurance.reasons?.[0]||'Inside training-profile bounds';
  $('command').textContent=(r.recent_command.name||'No command').replaceAll('_',' ');
  $('command-note').textContent=`${r.recent_command.status} • ${Math.round((r.recent_command.seconds_since_command||0)/60)} min earlier`;
  $('position').textContent=`${state.index+1} / ${state.records.length}`;
  document.querySelectorAll('.scenario-buttons button').forEach(b=>b.classList.toggle('active',b.textContent===status));
  renderSubsystems(r); renderProbabilities(r); renderEvidence(r); renderTelemetry(r);
}

function renderOverallExplanation(r){
  const overall=r.overall_health;
  const subsystemStatuses=Object.values(overall.subsystem_statuses||{});
  const mlOnly=overall.contributors.length===1&&overall.contributors[0]==='ml_classifier';
  const allSubsystemsHealthy=subsystemStatuses.length>0&&subsystemStatuses.every(status=>status==='Healthy');

  if(mlOnly&&overall.status!=='Healthy'){
    const ruleContext=allSubsystemsHealthy
      ? 'no subsystem rule violations'
      : `subsystem rules remained below ${overall.status}`;
    $('contributors').textContent=`ML-only anomaly; ${ruleContext}. The accepted classifier prediction raised overall health to ${overall.status}.`;
    return;
  }

  $('contributors').textContent=`Driven by ${overall.contributors.map(x=>x.replaceAll('_',' ')).join(', ')||'subsystem assessment'}`;
}

function renderSubsystems(r){
  $('subsystems').innerHTML='';
  Object.entries(r.overall_health.subsystem_statuses).forEach(([key,value])=>{
    const item=document.createElement('div'); item.className='subsystem';
    item.innerHTML=`<span>${names[key]||key.replaceAll('_',' ')}</span><span class="pill ${value}">${value}</span>`;
    $('subsystems').appendChild(item);
  });
}

function renderProbabilities(r){
  $('probabilities').innerHTML='';
  Object.entries(r.class_probabilities).sort((a,b)=>b[1]-a[1]).forEach(([key,value])=>{
    const pct=Math.round(value*100), row=document.createElement('div'); row.className='prob-row';
    row.innerHTML=`<span class="${key}">${key}</span><div class="prob-track"><i style="width:${pct}%;background:${colors[key]}"></i></div><strong>${pct}%</strong>`;
    $('probabilities').appendChild(row);
  });
  $('recommendations').innerHTML=(r.recommendations||[]).slice(0,4).map(x=>`<li>${x}</li>`).join('');
}

function renderEvidence(r){
  const evidence=[];
  const statuses=Object.values(r.overall_health.subsystem_statuses||{});
  const mlOnly=r.overall_health.contributors.length===1&&r.overall_health.contributors[0]==='ml_classifier';
  const allSubsystemsHealthy=statuses.length>0&&statuses.every(status=>status==='Healthy');

  if(mlOnly&&r.overall_health.status!=='Healthy'){
    const ranked=Object.entries(r.class_probabilities||{}).sort((a,b)=>b[1]-a[1]);
    const top=ranked[0],runnerUp=ranked[1];
    const topText=top?`${top[0]} ${Math.round(top[1]*100)}%`:'unavailable';
    const runnerUpText=runnerUp?`, versus ${runnerUp[0]} ${Math.round(runnerUp[1]*100)}%`:'';
    const ruleContext=allSubsystemsHealthy
      ? 'All displayed subsystem rules remained Healthy.'
      : `Any displayed subsystem rule findings remained below ${r.overall_health.status} severity.`;
    evidence.push({
      subsystem:'ML-only assessment',
      parameter:'classifier votes',
      message:`The model output was ${topText}${runnerUpText}. ${ruleContext} Per-feature attribution is not available, so this identifies a multivariate pattern rather than a specific failed component.`
    });
  }
  Object.entries(r.subsystem_health).forEach(([subsystem,assessment])=>(assessment.evidence||[]).forEach(e=>evidence.push({...e,subsystem})));
  if(!evidence.length) evidence.push(...(r.assessment||[]).slice(0,3).map(message=>({subsystem:'nominal assessment',message})));
  $('evidence').innerHTML=evidence.slice(0,6).map(e=>`<div class="evidence-item"><strong>${(names[e.subsystem]||e.subsystem).replaceAll('_',' ')} • ${e.parameter||'system check'}</strong><span>${e.message}${e.observed_value!==undefined?` Observed: ${safe(e.observed_value)}.`:''}</span></div>`).join('');
}

function renderTelemetry(r){
  const priority=['battery_voltage_v','battery_current_a','battery_state_of_charge_pct','solar_array_current_a','flight_computer_temperature_c','payload_temperature_c','reaction_wheel_1_speed_rpm','downlink_rate_kbps','memory_usage_pct','propellant_remaining_pct','clock_drift_us_day','command_queue_depth'];
  $('telemetry').innerHTML=priority.map(k=>`<div><span>${k.replaceAll('_',' ')}</span><strong>${safe(r.telemetry[k])}</strong></div>`).join('');
}

$('previous').onclick=()=>render(state.index-1); $('next').onclick=()=>render(state.index+1);
$('play').onclick=()=>{if(state.timer){clearInterval(state.timer);state.timer=null;$('play').textContent='▶ Run timeline'}else{state.timer=setInterval(()=>render(state.index+1),1800);$('play').textContent='■ Pause timeline'}};
$('details').onclick=()=>{const hidden=$('telemetry').classList.toggle('hidden');$('details').textContent=hidden?'Show telemetry details':'Hide telemetry details'};
document.addEventListener('keydown',e=>{if(e.key==='ArrowRight')render(state.index+1);if(e.key==='ArrowLeft')render(state.index-1)});
if(!window.matchMedia('(prefers-reduced-motion: reduce)').matches){
  window.addEventListener('scroll',()=>{
    const y=window.scrollY;
    document.documentElement.style.setProperty('--stars-near',`${y*.09}px`);
    document.documentElement.style.setProperty('--stars-far',`${y*.035}px`);
    document.documentElement.style.setProperty('--station-shift',`${y*.06}px`);
    document.documentElement.style.setProperty('--planet-shift',`${y*.025}px`);
  },{passive:true});
}
load();
