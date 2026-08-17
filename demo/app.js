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

function setStatus(domain, value, note) {
  $(`${domain}-status`).textContent = text(value);
  $(`${domain}-dot`).style.background = tone(value);
  $(`${domain}-dot`).style.boxShadow = `0 0 10px ${tone(value)}`;
  $(`${domain}-note`).textContent = note;
}

function render(payload) {
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
load();
