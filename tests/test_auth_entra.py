"""Testes de ``auth/entra.py`` — 100% offline.

Nenhum destes testes fala com o Entra real: as fixtures de
``tests/conftest.py`` (``entra_chave_privada``/``entra_jwk_publico``/
``entra_fazer_token``/``entra_habilitar``) geram um par RSA de teste,
assinam JWTs com ele e mockam (via ``respx``) o endpoint de JWKS do Entra
devolvendo a chave pública correspondente.
"""
from __future__ import annotations

import httpx
import jwt as pyjwt
import pytest
import respx

from mcp_radardeprecos.auth import entra
from tests.conftest import ENTRA_CLIENT_TESTE, ENTRA_JWKS_URL_TESTE, ENTRA_TENANT_TESTE


def _mockar_jwks(mock: respx.MockRouter, jwk: dict, *, url: str = ENTRA_JWKS_URL_TESTE) -> None:
    mock.get(url).mock(return_value=httpx.Response(200, json={"keys": [jwk]}))


async def test_token_valido_e_aceito(entra_habilitar, entra_jwk_publico, entra_fazer_token):
    entra_habilitar()
    with respx.mock(assert_all_called=False) as mock:
        _mockar_jwks(mock, entra_jwk_publico)
        claims = await entra.validar_token(entra_fazer_token())
    assert claims["sub"] == "usuario-teste"
    assert claims["aud"] == ENTRA_CLIENT_TESTE


async def test_token_expirado_e_rejeitado(entra_habilitar, entra_jwk_publico, entra_fazer_token):
    entra_habilitar()
    token = entra_fazer_token(exp=0)
    with respx.mock(assert_all_called=False) as mock:
        _mockar_jwks(mock, entra_jwk_publico)
        with pytest.raises(entra.EntraAuthError, match="expirado"):
            await entra.validar_token(token)


async def test_token_ainda_nao_valido_nbf_e_rejeitado(entra_habilitar, entra_jwk_publico, entra_fazer_token):
    import time

    entra_habilitar()
    token = entra_fazer_token(nbf=int(time.time()) + 3600)
    with respx.mock(assert_all_called=False) as mock:
        _mockar_jwks(mock, entra_jwk_publico)
        with pytest.raises(entra.EntraAuthError, match="nbf"):
            await entra.validar_token(token)


async def test_audience_errada_e_rejeitada(entra_habilitar, entra_jwk_publico, entra_fazer_token):
    entra_habilitar()
    token = entra_fazer_token(aud="outro-client-id")
    with respx.mock(assert_all_called=False) as mock:
        _mockar_jwks(mock, entra_jwk_publico)
        with pytest.raises(entra.EntraAuthError, match="audience"):
            await entra.validar_token(token)


async def test_issuer_errado_e_rejeitado(entra_habilitar, entra_jwk_publico, entra_fazer_token):
    entra_habilitar()
    token = entra_fazer_token(iss="https://evil.example/tenant-teste/v2.0")
    with respx.mock(assert_all_called=False) as mock:
        _mockar_jwks(mock, entra_jwk_publico)
        with pytest.raises(entra.EntraAuthError, match="issuer"):
            await entra.validar_token(token)


async def test_issuer_variante_sts_windows_net_e_aceito(entra_habilitar, entra_jwk_publico, entra_fazer_token):
    # O Entra emite duas variantes de `iss` válidas para o mesmo tenant —
    # ver docstring de auth.entra._issuers_aceitos.
    entra_habilitar()
    token = entra_fazer_token(iss=f"https://sts.windows.net/{ENTRA_TENANT_TESTE}/")
    with respx.mock(assert_all_called=False) as mock:
        _mockar_jwks(mock, entra_jwk_publico)
        claims = await entra.validar_token(token)
    assert claims["iss"] == f"https://sts.windows.net/{ENTRA_TENANT_TESTE}/"


async def test_assinatura_invalida_e_rejeitada(entra_habilitar, entra_jwk_publico, entra_fazer_token):
    # Token assinado com uma chave DIFERENTE da que está na JWKS mockada —
    # mesmo kid no header (o servidor confia no conteúdo do JWKS, não no
    # header do token, para decidir qual chave usar).
    from cryptography.hazmat.primitives.asymmetric import rsa

    entra_habilitar()
    outra_chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = pyjwt.encode(
        {
            "aud": ENTRA_CLIENT_TESTE,
            "iss": f"https://login.microsoftonline.com/{ENTRA_TENANT_TESTE}/v2.0",
            "exp": 9999999999,
            "nbf": 0,
        },
        outra_chave,
        algorithm="RS256",
        headers={"kid": "test-kid-1"},
    )
    with respx.mock(assert_all_called=False) as mock:
        _mockar_jwks(mock, entra_jwk_publico)
        with pytest.raises(entra.EntraAuthError, match="assinatura"):
            await entra.validar_token(token)


async def test_token_sem_kid_e_rejeitado(entra_habilitar, entra_chave_privada):
    entra_habilitar()
    token = pyjwt.encode(
        {
            "aud": ENTRA_CLIENT_TESTE,
            "iss": f"https://login.microsoftonline.com/{ENTRA_TENANT_TESTE}/v2.0",
            "exp": 9999999999,
            "nbf": 0,
        },
        entra_chave_privada,
        algorithm="RS256",
        # sem header kid
    )
    with pytest.raises(entra.EntraAuthError, match="kid"):
        await entra.validar_token(token)


async def test_sem_header_authorization_no_middleware_nao_aplica_aqui_token_malformado_e_rejeitado(entra_habilitar):
    entra_habilitar()
    with pytest.raises(entra.EntraAuthError, match="malformado"):
        await entra.validar_token("isto-nao-e-um-jwt")


async def test_kid_desconhecido_dispara_refresh_da_jwks_e_entao_valida(
    entra_habilitar, entra_jwk_publico, entra_fazer_token
):
    # Regressão de rotação de chave: o cache já tem uma JWKS (com a chave
    # de teste), mas o Entra "rotacionou" e a próxima busca já traria essa
    # mesma chave OK — aqui simulamos o caminho onde o cache ainda não
    # tinha nada e a primeira busca já encontra o kid certo (o caso comum);
    # o teste de rotação de fato (cache com um kid diferente) está no teste
    # seguinte.
    entra_habilitar()
    with respx.mock(assert_all_called=False) as mock:
        _mockar_jwks(mock, entra_jwk_publico)
        claims = await entra.validar_token(entra_fazer_token())
    assert claims["sub"] == "usuario-teste"


async def test_rotacao_de_chave_jwks_muda_entre_duas_chamadas(entra_habilitar, entra_chave_privada):
    # Cenário completo de rotação: primeira chamada cacheia a JWKS só com
    # kid-antigo; um segundo token chega assinado com kid-novo (ainda não
    # cacheado) — o cache precisa perceber que o kid é desconhecido e
    # refazer a busca, que desta vez (Entra já rotacionou) traz os dois.
    import json
    import time

    from cryptography.hazmat.primitives.asymmetric import rsa

    entra_habilitar()

    chave_nova = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk_antigo = json.loads(pyjwt.algorithms.RSAAlgorithm.to_jwk(entra_chave_privada.public_key()))
    jwk_antigo.update(kid="kid-antigo", use="sig", alg="RS256")
    jwk_novo = json.loads(pyjwt.algorithms.RSAAlgorithm.to_jwk(chave_nova.public_key()))
    jwk_novo.update(kid="kid-novo", use="sig", alg="RS256")

    agora = int(time.time())
    claims_base = {
        "aud": ENTRA_CLIENT_TESTE,
        "iss": f"https://login.microsoftonline.com/{ENTRA_TENANT_TESTE}/v2.0",
        "exp": agora + 3600,
        "nbf": agora - 10,
    }
    token_antigo = pyjwt.encode(
        {**claims_base, "sub": "u-antigo"}, entra_chave_privada, algorithm="RS256",
        headers={"kid": "kid-antigo"},
    )
    token_novo = pyjwt.encode(
        {**claims_base, "sub": "u-novo"}, chave_nova, algorithm="RS256",
        headers={"kid": "kid-novo"},
    )

    chamadas = {"n": 0}

    def responder(request):
        chamadas["n"] += 1
        chaves = [jwk_antigo] if chamadas["n"] == 1 else [jwk_antigo, jwk_novo]
        return httpx.Response(200, json={"keys": chaves})

    with respx.mock(assert_all_called=False) as mock:
        mock.get(ENTRA_JWKS_URL_TESTE).mock(side_effect=responder)

        primeiro = await entra.validar_token(token_antigo)
        assert primeiro["sub"] == "u-antigo"
        assert chamadas["n"] == 1

        segundo = await entra.validar_token(token_novo)
        assert segundo["sub"] == "u-novo"
        assert chamadas["n"] == 2  # refresh disparado pelo kid desconhecido


async def test_kid_ausente_mesmo_apos_refresh_e_rejeitado(entra_habilitar, entra_jwk_publico, entra_fazer_token):
    entra_habilitar()
    token = entra_fazer_token(_kid="kid-que-nunca-existiu")
    with respx.mock(assert_all_called=False) as mock:
        _mockar_jwks(mock, entra_jwk_publico)
        with pytest.raises(entra.EntraAuthError, match="não encontrado"):
            await entra.validar_token(token)


async def test_jwks_indisponivel_por_erro_de_rede_nao_vira_401(entra_habilitar, entra_fazer_token):
    entra_habilitar()
    token = entra_fazer_token()
    with respx.mock(assert_all_called=False) as mock:
        mock.get(ENTRA_JWKS_URL_TESTE).mock(side_effect=httpx.ConnectError("instabilidade"))
        with pytest.raises(entra.EntraJWKSIndisponivelError):
            await entra.validar_token(token)


async def test_scope_exigido_ausente_e_rejeitado(entra_habilitar, entra_jwk_publico, entra_fazer_token):
    entra_habilitar(entra_required_scope="Leitura.Tools")
    token = entra_fazer_token()  # sem 'scp' nem 'roles'
    with respx.mock(assert_all_called=False) as mock:
        _mockar_jwks(mock, entra_jwk_publico)
        with pytest.raises(entra.EntraAuthError, match="scope"):
            await entra.validar_token(token)


async def test_scope_exigido_presente_via_scp_e_aceito(entra_habilitar, entra_jwk_publico, entra_fazer_token):
    entra_habilitar(entra_required_scope="Leitura.Tools")
    token = entra_fazer_token(scp="Leitura.Tools Outro.Scope")
    with respx.mock(assert_all_called=False) as mock:
        _mockar_jwks(mock, entra_jwk_publico)
        claims = await entra.validar_token(token)
    assert "Leitura.Tools" in claims["scp"]


async def test_scope_exigido_presente_via_roles_e_aceito(entra_habilitar, entra_jwk_publico, entra_fazer_token):
    # Tokens de aplicação (client credentials) usam 'roles', não 'scp'.
    entra_habilitar(entra_required_scope="Leitura.Tools")
    token = entra_fazer_token(roles=["Leitura.Tools"])
    with respx.mock(assert_all_called=False) as mock:
        _mockar_jwks(mock, entra_jwk_publico)
        claims = await entra.validar_token(token)
    assert claims["roles"] == ["Leitura.Tools"]


async def test_validar_token_sem_settings_configuradas_levanta_runtimeerror(entra_fazer_token):
    # Regressão-chave: sem entra_tenant_id/entra_client_id (comportamento
    # padrão do projeto, sem nenhuma variável de ambiente Entra setada),
    # validar_token nunca deveria ser chamado de verdade — mas se for (erro
    # de programação), falha alto e claro em vez de continuar com tenant
    # None e mascarar o problema.
    from mcp_radardeprecos.auth import entra as entra_module

    assert entra_module.settings.entra_tenant_id is None
    assert entra_module.settings.entra_client_id is None
    with pytest.raises(RuntimeError, match="ENTRA_TENANT_ID"):
        await entra.validar_token(entra_fazer_token())
