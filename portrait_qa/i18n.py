"""Texts of the setup window (pt-BR / en). Kept apart from Tk so they can be tested anywhere."""

from __future__ import annotations

import ctypes
import locale
import os
import sys

TEXTS = {
    "pt": {
        "title": "Portrait QA: configuração do serviço",
        "service": "Serviço",
        "status": {
            "not_installed": "não instalado",
            "stopped": "parado",
            "starting": "iniciando…",
            "running": "rodando",
            "stopping": "parando…",
            "unknown": "indisponível neste sistema",
        },
        "access": "Acesso",
        "local": "Somente este computador (127.0.0.1)",
        "network": "Rede (outros computadores podem acessar)",
        "port": "Porta",
        "check": "Verificar",
        "api_key": "Chave da API",
        "generate": "Gerar",
        "show": "Mostrar",
        "key_hint": "Obrigatória no modo rede. Enviada no cabeçalho X-API-Key.",
        "firewall": "Liberar a porta no Firewall do Windows",
        "apply_install": "Instalar e iniciar",
        "apply_update": "Aplicar e reiniciar",
        "stop": "Parar",
        "uninstall": "Desinstalar",
        "endpoints": "Endpoints",
        "copy": "Copiar",
        "copied": "Copiado: {url}",
        "open_test": "Abrir página de teste",
        "open_docs": "Documentação (/docs)",
        "open_logs": "Pasta de logs",
        "open_config": "Abrir config.json",
        "port_free": "Porta {port} livre.",
        "port_ours": "Porta {port} em uso por este serviço (versão {version}).",
        "port_busy": "Porta {port} em uso por outro programa{detail}.",
        "port_suggest": " Sugestão: {suggestion}.",
        "use_suggestion": "Usar {suggestion}",
        "port_range": "A porta deve estar entre 1 e 65535.",
        "key_required": "No modo rede a chave da API é obrigatória (mínimo {min} caracteres). Use “Gerar”.",
        "key_short": "A chave da API deve ter pelo menos {min} caracteres ASCII.",
        "no_health": "O serviço iniciou mas não respondeu em /v1/health na porta {port}. Veja a pasta de logs.",
        "saving": "Gravando {path}…",
        "installing": "Instalando o serviço…",
        "installed": "Serviço instalado.",
        "updated": "Serviço atualizado.",
        "stopping": "Parando o serviço…",
        "starting": "Iniciando o serviço…",
        "waiting_health": "Aguardando o serviço responder…",
        "firewall_step": "Liberando a porta {port} no firewall…",
        "done": "Pronto. O serviço está respondendo.",
        "stopped_msg": "Serviço parado.",
        "uninstall_confirm": "Remover o serviço Portrait QA deste computador?\n\nO config.json e os logs são mantidos.",
        "uninstalled": "Serviço removido.",
        "not_admin": "Abra este programa como administrador para instalar ou alterar o serviço.",
        "not_windows": "O serviço do Windows só está disponível no Windows. Use “portrait-qa serve”.",
        "error": "Erro",
        "port_number": "Informe um número de porta.",
    },
    "en": {
        "title": "Portrait QA: service setup",
        "service": "Service",
        "status": {
            "not_installed": "not installed",
            "stopped": "stopped",
            "starting": "starting…",
            "running": "running",
            "stopping": "stopping…",
            "unknown": "not available on this system",
        },
        "access": "Access",
        "local": "This computer only (127.0.0.1)",
        "network": "Network (other computers can connect)",
        "port": "Port",
        "check": "Check",
        "api_key": "API key",
        "generate": "Generate",
        "show": "Show",
        "key_hint": "Required in network mode. Sent in the X-API-Key header.",
        "firewall": "Open the port in Windows Firewall",
        "apply_install": "Install and start",
        "apply_update": "Apply and restart",
        "stop": "Stop",
        "uninstall": "Uninstall",
        "endpoints": "Endpoints",
        "copy": "Copy",
        "copied": "Copied: {url}",
        "open_test": "Open test page",
        "open_docs": "API docs (/docs)",
        "open_logs": "Log folder",
        "open_config": "Open config.json",
        "port_free": "Port {port} is free.",
        "port_ours": "Port {port} is used by this service (version {version}).",
        "port_busy": "Port {port} is used by another program{detail}.",
        "port_suggest": " Suggestion: {suggestion}.",
        "use_suggestion": "Use {suggestion}",
        "port_range": "The port must be between 1 and 65535.",
        "key_required": "Network mode needs an API key (at least {min} characters). Use “Generate”.",
        "key_short": "The API key must have at least {min} ASCII characters.",
        "no_health": "The service started but did not answer /v1/health on port {port}. See the log folder.",
        "saving": "Writing {path}…",
        "installing": "Installing the service…",
        "installed": "Service installed.",
        "updated": "Service updated.",
        "stopping": "Stopping the service…",
        "starting": "Starting the service…",
        "waiting_health": "Waiting for the service to answer…",
        "firewall_step": "Opening port {port} in the firewall…",
        "done": "Done. The service is answering.",
        "stopped_msg": "Service stopped.",
        "uninstall_confirm": "Remove the Portrait QA service from this computer?\n\nconfig.json and the logs are kept.",
        "uninstalled": "Service removed.",
        "not_admin": "Run this program as administrator to install or change the service.",
        "not_windows": "The Windows service is only available on Windows. Use “portrait-qa serve”.",
        "error": "Error",
        "port_number": "Enter a port number.",
    },
}


def detect_language() -> str:
    lang = ""
    if sys.platform == "win32":
        try:
            lang = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "")
        except (AttributeError, OSError):
            lang = ""
    if not lang:
        lang = (locale.getlocale()[0] or os.environ.get("LANG", "")).lower()
    return "pt" if lang.lower().startswith("pt") else "en"
