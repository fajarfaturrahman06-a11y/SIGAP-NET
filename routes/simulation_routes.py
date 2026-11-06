from flask import Blueprint, redirect, url_for, flash

from authz import login_required, roles_required, current_user
from csrf import csrf_protect
from services import simulation

simulation_bp = Blueprint('simulation', __name__)


@simulation_bp.route('/settings/simulation/run/<scenario>', methods=['POST'])
@login_required
@roles_required('admin', 'operator')
@csrf_protect
def run(scenario):
    try:
        result = simulation.run_scenario(scenario, actor=current_user())
        check = result['check']
        incident = result['incident']
        if incident:
            reused = getattr(incident, 'was_reused', False)
            flash(f"{result['scenario']['title']} selesai. Risiko "
                  f"{check.highest_risk}, insiden {incident.code} "
                  f"{'diperbarui (drift berulang).' if reused else 'dibuat.'}",
                  'warning')
        else:
            flash(f"{result['scenario']['title']} selesai. Risiko "
                  f"{check.highest_risk}, {check.change_count} perubahan.", 'info')
        return redirect(url_for('checks.detail', check_id=check.id))
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('settings'))


@simulation_bp.route('/settings/simulation/reset', methods=['POST'])
@login_required
@roles_required('admin')
@csrf_protect
def reset():
    simulation.reset_demo(actor=None)
    flash('Data demo berhasil direset. Audit trail tetap tersimpan.', 'success')
    return redirect(url_for('settings'))
