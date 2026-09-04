from sos.services import mode_transition_plan as _mode_transition_plan_service


def run(request):
    return _mode_transition_plan_service.run(request)
