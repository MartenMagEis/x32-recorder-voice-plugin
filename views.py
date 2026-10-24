"""Review page for the collected voice samples - mounted by x32-recorder under
/plugins/<name>/ (see urls.py), linked from the plugin's settings."""
import json
from pathlib import Path

from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import sample_store

PAGE = Path(__file__).with_name("review.html")


@require_GET
def review_page(request):
    return HttpResponse(PAGE.read_text(encoding="utf-8"), content_type="text/html; charset=utf-8")


@require_GET
def sample_list(request):
    return JsonResponse({"samples": sample_store.list_samples(only_open=request.GET.get("all") != "1")})


@require_GET
def sample_audio(request, rel):
    base = sample_store.resolve(rel)
    if base is None or not base.with_suffix(".wav").is_file():
        raise Http404
    return FileResponse(open(base.with_suffix(".wav"), "rb"), content_type="audio/wav")


def _body(request):
    try:
        return json.loads(request.body or b"{}")
    except ValueError:
        return {}


@csrf_exempt
@require_POST
def sample_label(request):
    data = _body(request)
    if not sample_store.set_label(data.get("id"), data.get("label")):
        return JsonResponse({"error": "Unbekannter Clip oder ungültige Bewertung"}, status=400)
    return JsonResponse({"ok": True})


@csrf_exempt
@require_POST
def sample_delete(request):
    if not sample_store.delete(_body(request).get("id")):
        return JsonResponse({"error": "Unbekannter Clip"}, status=400)
    return JsonResponse({"ok": True})
