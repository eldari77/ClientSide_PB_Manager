from sos.services import conveyor as _conveyor_service


def run(request):
    return _conveyor_service.run(request)
