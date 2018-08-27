import uuid
import json
import base64
import hashlib
import hmac

from django.contrib.auth import get_user_model
from django.contrib.auth import login, logout
from django.http import HttpResponse, HttpResponseRedirect, QueryDict
from django.conf import settings
from django.urls import reverse
from django.utils.http import urlencode

User = get_user_model()

def sso_redirect_to_provider(request):
    if request.user.is_authenticated:
        return HttpResponseRedirect(request.GET.get('next', '/'))

    nonce = uuid.uuid4().hex
    secret = settings.DISCOURSE_SSO_SECRET.encode('utf8')
    provider = settings.DISCOURSE_SSO_PROVIDER

    request.session['sso_nonce'] = nonce

    params = request.GET.copy()
    try:
        del params['sso']
        del params['sig']
    except KeyError:
        pass
    if params:
        params = '?' + params.urlencode()
    else:
        params = ''

    return_path = reverse('sso_callback') + params
    return_url = request.build_absolute_uri(return_path)

    payload = QueryDict(mutable=True)
    payload['nonce'] = nonce
    payload['return_sso_url'] = return_url
    payload = base64.b64encode(payload.urlencode().encode('utf8'))

    signature = hmac.new(
        secret, msg=payload, digestmod=hashlib.sha256).hexdigest()

    provider_url = 'https://%s/session/sso_provider?sso=%s&sig=%s' % (
        provider, payload.decode('utf8'), signature)

    return HttpResponseRedirect(provider_url)


def sso_client_callback(request):
    try:
        payload = request.GET['sso'].encode('utf8')
        signature = request.GET['sig']
    except KeyError:
        return HttpResponse("This request was not signed.",
                            status=422)

    secret = settings.DISCOURSE_SSO_SECRET.encode('utf8')
    exp_signature = hmac.new(
        secret, msg=payload, digestmod=hashlib.sha256).hexdigest()
    if exp_signature != signature:
        return HttpResponse("Request signature does not match expected.",
                            status=422)

    payload = QueryDict(base64.b64decode(payload).decode('utf8'))
    nonce = payload['nonce']
    try:
        exp_nonce = request.session.pop('sso_nonce')
    except KeyError:
        return HttpResponse("Invalid session.",
                            status=422)
    if nonce != exp_nonce:
        return HttpResponse("Login replay detected.",
                            status=422)

    user, created = User.objects.get_or_create(username=payload['username'])
    if created:
        user.set_unusable_password()
    login(request, user)

    return HttpResponseRedirect(request.GET.get('next', '/'))


def sso_client_logout(request):
    logout(request)
    return HttpResponseRedirect(request.GET.get('next', '/'))