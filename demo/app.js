const $ = id => document.getElementById(id);
const labels = {
  clear_match: 'Clear match', ambiguous: 'Ambiguous identity', no_candidate_above_threshold: 'No match',
  complete: 'Complete', geometric_only: 'Geometry only', abstained: 'Abstained',
  advisory_ready: 'Advisory ready', limited: 'Limited', insufficient_evidence: 'Insufficient evidence'
};
const coaNames = {
  COA_IMPROVE_DEGRADED_EVIDENCE: 'Improve degraded evidence',
  COA_REFINE_TRACKING: 'Refine tracking solution',
  COA_MANEUVER_PLANNING_REVIEW: 'Begin maneuver planning review',
  COA_RESOLVE_WITHHELD_EVIDENCE: 'Resolve withheld evidence'
};
const tone = value => value === 'usable' || value === 'complete' || value === 'Healthy' || value === 'clear_match'
  ? 'var(--green)' : value === 'withheld' || value === 'abstained' || value === 'insufficient_evidence'
    ? 'var(--red)' : 'var(--amber)';
const text = value => labels[value] || value || 'Unknown';
const esc = value => String(value ?? '—').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
const pct = value => value === null || value === undefined ? '—' : `${(Number(value) * 100).toFixed(2)}%`;
const number = (value, digits = 3) => value === null || value === undefined ? '—' : Number(value).toFixed(digits);
let dashboardPayload = null;

function hero(items) {
  return `<div class="detail-hero">${items.map(([label, value]) => `<div><small>${esc(label)}</small><strong>${esc(value)}</strong></div>`).join('')}</div>`;
}

function detailGrid(items) {
  return `<div class="detail-grid">${items.map(([label, value]) => `<div class="detail-item"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join('')}</div>`;
}

function bulletList(items, empty = 'No findings reported.') {
  const values = (items || []).filter(Boolean);
  return `<ul class="detail-list">${values.length ? values.map(item => `<li>${esc(item)}</li>`).join('') : `<li>${esc(empty)}</li>`}</ul>`;
}

function renderHealthReport(report) {
  const assurance = report.model_assurance || {};
  const subsystems = Object.entries(report.subsystem_health || {});
  const telemetry = Object.entries(report.telemetry || {}).filter(([, value]) => value !== null).slice(0, 18);
  return hero([
    ['Overall health', report.overall_health?.status], ['ML prediction', report.prediction],
    ['Model assurance', assurance.decision], ['Prediction confidence', pct(report.predicted_probability)]
  ]) + `<div class="detail-layout">
    <section class="detail-section wide"><h4>Subsystem assessments</h4><table class="detail-table"><thead><tr><th>Subsystem</th><th>Status</th><th>Confidence</th><th>Method</th><th>Completeness</th></tr></thead><tbody>${subsystems.map(([name, item]) => `<tr><td>${esc(name.replaceAll('_',' '))}</td><td class="${esc(item.status?.toLowerCase())}">${esc(item.status)}</td><td>${pct(item.confidence)}</td><td>${esc(item.method)}</td><td>${esc(item.data_completeness?.available_measurements)} / ${esc(item.data_completeness?.required_measurements)}</td></tr>`).join('')}</tbody></table></section>
    <section class="detail-section"><h4>Data and model assurance</h4>${detailGrid([
      ['Data quality', report.data_quality?.status], ['Model accepted', assurance.accepted ? 'Yes' : 'No'],
      ['Assurance method', assurance.method], ['Report time', report.report_generated_at],
      ['Telemetry time', report.timestamp], ['Recommendation scope', report.recommendation_scope]
    ])}</section>
    <section class="detail-section"><h4>Recommendations</h4>${bulletList(report.recommendations)}</section>
    <section class="detail-section wide"><h4>Telemetry snapshot</h4>${detailGrid(telemetry.map(([key, value]) => [key.replaceAll('_',' '), value]))}</section>
  </div>`;
}

function renderIdentityReport(report) {
  const prediction = report.prediction || {};
  const selection = prediction.candidate_selection || {};
  const rankings = prediction.candidate_rankings || [];
  return hero([
    ['Decision', selection.decision_basis], ['Canonical identity', prediction.canonical_object_id],
    ['Match score', number(prediction.match_score, 6)], ['Prototype threshold', prediction.threshold?.value]
  ]) + `<div class="detail-layout">
    <section class="detail-section wide"><h4>Ranked candidates</h4><table class="detail-table"><thead><tr><th>Rank</th><th>Object</th><th>Score</th><th>Position residual</th><th>Velocity residual</th><th>Threshold</th></tr></thead><tbody>${rankings.map(item => `<tr><td>${esc(item.rank)}</td><td>${esc(item.canonical_object_id)}</td><td>${number(item.match_score, 6)}</td><td>${number(item.position_residual_km, 4)} km</td><td>${number(item.velocity_residual_km_s, 6)} km/s</td><td>${item.meets_threshold ? 'Met' : 'Not met'}</td></tr>`).join('')}</tbody></table></section>
    <section class="detail-section"><h4>Observation and provenance</h4>${detailGrid([
      ['Observation', prediction.observation_id], ['Observed at', prediction.observation_timestamp],
      ['Catalog source', prediction.catalog_provenance?.catalog_source], ['Catalog record', prediction.catalog_provenance?.catalog_record_id],
      ['Affiliation', prediction.affiliation], ['Affiliation authority', prediction.affiliation_provenance?.affiliation_authority]
    ])}</section>
    <section class="detail-section"><h4>Selection rationale</h4>${bulletList(prediction.rationale)}</section>
  </div>`;
}

function renderCollisionReport(report) {
  const closest = report.closest_approach || {};
  const probability = report.probability || {};
  return hero([
    ['Assessment', report.assessment_status], ['Risk level', report.risk?.level],
    ['Miss distance', `${number(closest.miss_distance_km, 6)} km`], ['Collision probability', pct(probability.collision_probability)]
  ]) + `<div class="detail-layout">
    <section class="detail-section"><h4>Encounter geometry</h4>${detailGrid([
      ['Closest approach', closest.time_of_closest_approach], ['Relative velocity', `${number(closest.relative_velocity_km_s, 6)} km/s`],
      ['Geometry method', closest.method?.name], ['Primary object', report.primary_object_id],
      ['Secondary object', report.secondary_object_id], ['Assessment ID', report.assessment_id]
    ])}</section>
    <section class="detail-section"><h4>Probability and uncertainty</h4>${detailGrid([
      ['Probability status', probability.status], ['Hard-body radius', `${number(probability.hard_body_radius_m, 1)} m`],
      ['Probability method', probability.method?.name], ['Validation', probability.method?.validation_status],
      ['Covariance status', report.uncertainty_assurance?.status], ['Covariance frame', report.uncertainty_assurance?.covariance_frame]
    ])}</section>
    <section class="detail-section"><h4>Assessment rationale</h4>${bulletList(report.rationale)}</section>
    <section class="detail-section"><h4>Uncertainty assumptions</h4>${bulletList(report.uncertainty_assurance?.assumptions)}</section>
  </div>`;
}

function renderCoaReport(report) {
  const trace = report.decision_tree?.trace || [];
  const candidates = report.candidate_coas || [];
  return hero([
    ['COA status', report.status], ['Decision scope', report.decision_scope],
    ['Terminal node', report.decision_tree?.terminal_node], ['Operator approval', 'Required for every candidate']
  ]) + `<div class="detail-layout">
    <section class="detail-section"><h4>Decision-tree trace</h4>${trace.map((item, index) => `<div class="trace-row"><span>${String(index + 1).padStart(2,'0')}</span><div><strong>${esc(item.question)}</strong><small>Observed: ${esc(item.observed_value)}</small></div><span class="trace-branch">${esc(item.branch)}</span></div>`).join('')}</section>
    <section class="detail-section"><h4>Operator summary</h4>${bulletList(report.operator_summary?.selection_basis)}<h4>Blocked actions</h4>${bulletList(report.blocked_actions)}</section>
    <section class="detail-section wide"><h4>Candidate actions and constraints</h4><table class="detail-table"><thead><tr><th>Course of action</th><th>Actions</th><th>Constraints</th><th>Disposition</th></tr></thead><tbody>${candidates.map(item => `<tr><td><strong>${esc(item.name)}</strong><br><span class="muted">${esc(item.rationale)}</span></td><td>${bulletList(item.actions)}</td><td>${bulletList(item.constraints)}</td><td>${esc(item.disposition?.replaceAll('_',' '))}<br>Approval: ${item.requires_operator_approval ? 'required' : 'not specified'}</td></tr>`).join('')}</tbody></table></section>
  </div>`;
}

function renderReport(kind) {
  if (!dashboardPayload) return;
  const renderers = {health: renderHealthReport, identity: renderIdentityReport, collision: renderCollisionReport, coa: renderCoaReport};
  $('report-detail').innerHTML = renderers[kind](dashboardPayload.details[kind]);
  document.querySelectorAll('.report-tab').forEach(button => {
    const active = button.dataset.report === kind;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
  });
}

function setStatus(domain, value, note) {
  $(`${domain}-status`).textContent = text(value);
  $(`${domain}-dot`).style.background = tone(value);
  $(`${domain}-dot`).style.boxShadow = `0 0 10px ${tone(value)}`;
  $(`${domain}-note`).textContent = note;
}

function render(payload) {
  dashboardPayload = payload;
  const {latest, summary, details} = payload;
  $('run-id').textContent = summary.run_id;
  $('spacecraft').textContent = summary.primary_spacecraft_id;
  $('scenario-label').textContent = summary.scenario_mode.replaceAll('_', ' ') + ' / ' + summary.orbital_source + ' orbital source';
  $('identity-track').textContent = summary.identified_secondary_object_id || summary.tracked_secondary_subject_id;
  $('published').textContent = new Date(latest.published_at).toLocaleString();
  $('contract').textContent = `v${summary.dashboard_contract_version}`;

  const healthNote = details.health.data_quality?.status === 'degraded'
    ? 'Health result available with degraded input quality.' : 'Subsystem result available for operator review.';
  setStatus('health', summary.health_status, healthNote);
  setStatus('identity', summary.object_identification_decision,
    summary.identified_secondary_object_id ? `Associated with ${summary.identified_secondary_object_id}. Affiliation does not establish intent.` : 'Canonical identity is withheld pending better evidence.');
  setStatus('collision', summary.collision_assessment_status,
    `${text(summary.collision_risk_level)} prototype risk. ${details.collision.risk?.basis || 'Review detailed evidence.'}`);
  setStatus('coa', summary.coa_status,
    summary.coa_status === 'limited' ? 'Planning support is available, but evidence limits action selection.' : 'Response options reflect the current evidence posture.');

  const evidenceDescriptions = {
    health: 'Spacecraft state and subsystem assessment',
    object_identification: 'Track association and catalog provenance',
    collision_risk: 'Closest approach and probability evidence'
  };
  $('evidence-list').innerHTML = Object.entries(summary.evidence_usability).map(([kind, usability]) => `
    <div class="evidence-row"><div><strong>${kind.replaceAll('_', ' ')}</strong><small>${evidenceDescriptions[kind]}</small></div><span class="usability ${usability}">${usability}</span></div>`).join('');
  const values = Object.values(summary.evidence_usability);
  $('overall-posture').textContent = values.includes('withheld') ? 'Blocked' : values.includes('degraded') ? 'Limited' : 'Usable';
  $('limitations').innerHTML = summary.limitations.map(item => `<li>${item}</li>`).join('');

  const candidates = details.coa.candidate_coas || [];
  $('coa-list').innerHTML = candidates.map((candidate, index) => {
    const code = candidate.code || summary.candidate_coa_codes[index];
    const description = candidate.rationale || candidate.description || 'Operator review is required before any response.';
    const type = candidate.disposition || (index === 0 ? 'Prerequisite' : 'Candidate');
    return `<li class="coa-item"><div><h4>${candidate.name || coaNames[code] || code.replaceAll('_', ' ')}</h4><p>${description}</p></div><span class="coa-type">${type.replaceAll('_', ' ')}</span></li>`;
  }).join('');
  renderReport('health');

  $('loading').hidden = true;
  $('error').hidden = true;
  $('dashboard').hidden = false;
}

function showError(error) {
  $('loading').hidden = true;
  $('dashboard').hidden = true;
  $('error').hidden = false;
  $('error-title').textContent = error.code === 'dashboard_version_unsupported' ? 'Contract version unsupported' : 'Validated run unavailable';
  $('error-message').textContent = error.message || 'The dashboard could not resolve a complete validated run.';
}

async function load() {
  $('error').hidden = true;
  $('loading').hidden = false;
  try {
    const response = await fetch('/api/dashboard', {cache: 'no-store'});
    const payload = await response.json();
    if (!response.ok) throw payload.error || {message: `Data service returned HTTP ${response.status}.`};
    render(payload);
  } catch (error) {
    showError(error);
  }
}

$('retry').addEventListener('click', load);
document.querySelectorAll('.report-tab').forEach(button => button.addEventListener('click', () => renderReport(button.dataset.report)));
load();
