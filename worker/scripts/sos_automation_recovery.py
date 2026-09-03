from sos.services import automation_recovery as _automation_recovery_service


def run(request):
    return _automation_recovery_service.run(request)
