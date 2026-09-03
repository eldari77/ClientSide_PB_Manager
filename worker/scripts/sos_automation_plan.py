from sos.services import automation_plan as _automation_plan_service


def run(request):
    return _automation_plan_service.run(request)
