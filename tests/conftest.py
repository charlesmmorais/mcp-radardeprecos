"""Configuração compartilhada dos testes.

Limpa o cache em memória (``utils/cache.py``) antes de cada teste — o cache é
um estado global de processo (dict de módulo), então sem isso um teste que
usa a mesma chave (CNPJ/ano/sequencial) de um teste anterior poderia receber
uma resposta cacheada em vez de bater no mock HTTP daquele teste
específico, mascarando o que o teste realmente está verificando. Isso cobre
também o cache de JWKS do Entra ID, que usa o mesmo módulo sob a
chave ``entra:jwks:{tenant}`` (ver ``auth/entra.py``).
"""
from __future__ import annotations

import dataclasses
import json
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from mcp_radardeprecos import config
from mcp_radardeprecos.utils import arquivo_saida, cache


@pytest.fixture(autouse=True)
def _limpar_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _restaurar_gravacao_em_disco():
    # `server._run_http` desliga a gravação em disco para o processo inteiro;
    # sem este reset, os testes que o chamam vazariam o estado para os seguintes.
    arquivo_saida.permitir_gravacao_em_disco(True)
    yield
    arquivo_saida.permitir_gravacao_em_disco(True)


# --- Auth Entra ID ---
#
# Fixtures compartilhadas entre tests/test_auth_entra.py e
# tests/test_auth_middleware.py: geração de um par de chaves RSA de teste
# (nunca a chave real de nenhum tenant Entra), fábrica de JWTs assinados com
# ela, e um helper para "ligar" a auth Entra nos módulos que a consultam.
#
# `auth/entra.py` faz `from ..config import settings` — isso copia a
# REFERÊNCIA do objeto `Settings()` no momento da importação; reatribuir
# `config.settings` depois não afeta o `settings` já importado dentro de
# `auth/entra.py`. Por isso o helper abaixo monkeypatcha diretamente o nome
# `settings` no módulo `auth.entra` (que é o único consultado por
# `validar_token`/`JWKSCache` — `auth/middleware.py` não lê settings, só
# delega para `validar_token`).
ENTRA_TENANT_TESTE = "tenant-teste"
ENTRA_CLIENT_TESTE = "client-teste"
ENTRA_KID_TESTE = "test-kid-1"
ENTRA_JWKS_URL_TESTE = f"https://login.microsoftonline.com/{ENTRA_TENANT_TESTE}/discovery/v2.0/keys"


@pytest.fixture(scope="session")
def entra_chave_privada() -> rsa.RSAPrivateKey:
    """Par de chaves RSA de teste — geração é cara (~dezenas de ms); nenhum teste muta a chave, então escopo de sessão é seguro."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def entra_jwk_publico(entra_chave_privada: rsa.RSAPrivateKey) -> dict[str, Any]:
    """JWK (dict) da chave pública de teste, com o ``kid`` que os tokens de teste usam — o formato que a JWKS do Entra devolveria."""
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(entra_chave_privada.public_key()))
    jwk.update(kid=ENTRA_KID_TESTE, use="sig", alg="RS256")
    return jwk


@pytest.fixture
def entra_fazer_token(entra_chave_privada: rsa.RSAPrivateKey):
    """Fábrica de JWTs de teste: ``entra_fazer_token(claim=valor, ...)`` sobrescreve claims padrão válidos.

    Aceita ``_kid`` (não vira claim) para simular um token assinado com um
    ``kid`` diferente do de :func:`entra_jwk_publico` — usado nos testes de
    ``kid`` desconhecido/rotação de chave.
    """

    def _fazer(**overrides: Any) -> str:
        agora = int(time.time())
        claims = {
            "aud": ENTRA_CLIENT_TESTE,
            "iss": f"https://login.microsoftonline.com/{ENTRA_TENANT_TESTE}/v2.0",
            "exp": agora + 3600,
            "nbf": agora - 10,
            "sub": "usuario-teste",
        }
        kid = overrides.pop("_kid", ENTRA_KID_TESTE)
        claims.update(overrides)
        return jwt.encode(claims, entra_chave_privada, algorithm="RS256", headers={"kid": kid})

    return _fazer


@pytest.fixture
def entra_habilitar(monkeypatch: pytest.MonkeyPatch):
    """Devolve ``habilitar(**overrides)``, que liga a auth Entra para o teste atual.

    Monkeypatcha o ``settings`` importado dentro de ``auth.entra`` (ver nota
    no topo do arquivo) com tenant/client de teste — sobrescrevíveis via
    kwargs (ex.: ``entra_habilitar(entra_required_scope="Leitura")``).
    """
    from mcp_radardeprecos.auth import entra as entra_module

    def habilitar(**overrides: Any) -> config.Settings:
        valores: dict[str, Any] = {
            "entra_tenant_id": ENTRA_TENANT_TESTE,
            "entra_client_id": ENTRA_CLIENT_TESTE,
        }
        valores.update(overrides)
        nova_settings = dataclasses.replace(config.settings, **valores)
        monkeypatch.setattr(entra_module, "settings", nova_settings)
        entra_module._resetar_caches_para_teste()
        return nova_settings

    return habilitar
