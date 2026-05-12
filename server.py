"""Site EcoDescarte (Flask). Na pasta do projeto:

    pip install -r requirements.txt
    python server.py

Local: http://127.0.0.1:PORT (PORT padrão 5000). Variáveis opcionais:
  PORT           — porta (Render injeta automaticamente).
  FLASK_RUN_HOST — padrão 127.0.0.1; use 0.0.0.0 para testar na LAN.
  FLASK_DEBUG    — 1/true para debug (não use em produção pública).

Produção (Render): o ``render.yaml`` usa Gunicorn; não depende deste ``app.run``.

API (JSON, opcional para outro front ou app):
  GET  /api/meta
  GET  /api/recomendar?zona=...&material=...   (material = código do resíduo)
  POST /api/recomendar  JSON {"zona":"...","material":"..."} ou form igual ao HTML.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from flask import Flask, jsonify, render_template, request

from Prototipo import (
    listar_materiais_do_banco,
    listar_regioes_do_banco,
    recomendar_ponto,
)

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True


def _materiais_lista() -> List[Dict[str, str]]:
    return [
        {"codigo": c, "nome": n} for c, n in listar_materiais_do_banco()
    ]


def _markers_para_mapa(resultado: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for idx, p in enumerate(resultado):
        lat, lon = p.get("lat"), p.get("lon")
        if lat is None or lon is None:
            continue
        out.append(
            {
                "lat": float(lat),
                "lng": float(lon),
                "nome": str(p.get("nome", "")),
                "pontuacao": p.get("pontuacao"),
                "destaque": idx == 0,
            }
        )
    return out


def _ponto_para_api(p: Dict[str, Any]) -> Dict[str, Any]:
    """Campos estáveis para JSON (consumo por app ou outro front no futuro)."""
    lat, lon = p.get("lat"), p.get("lon")
    out: Dict[str, Any] = {
        "nome": p.get("nome"),
        "endereco": p.get("endereco") or "",
        "zona": p.get("zona"),
        "nota": p.get("nota"),
        "pontuacao": p.get("pontuacao"),
        "lat": float(lat) if lat is not None else None,
        "lon": float(lon) if lon is not None else None,
        "aceita": list(p.get("aceita") or []),
    }
    det = p.get("pontuacao_detalhe")
    if isinstance(det, dict):
        out["pontuacao_detalhe"] = det
    return out


@app.route("/api/meta", methods=["GET"])
def api_meta():
    """Listas para montar formulários ou um front separado."""
    try:
        regioes = listar_regioes_do_banco()
        materiais = _materiais_lista()
    except Exception as e:
        return jsonify({"erro": str(e)}), 500
    return jsonify({"regioes": regioes, "materiais": materiais})


@app.route("/api/recomendar", methods=["GET", "POST"])
def api_recomendar():
    """Recomendação em JSON (híbrido: páginas HTML continuam em `/`)."""
    if request.method == "POST" and request.is_json:
        body = request.get_json(silent=True) or {}
        zona = (body.get("zona") or "").strip()
        material = (body.get("material") or "").strip()
    elif request.method == "POST":
        zona = (request.form.get("zona") or "").strip()
        material = (request.form.get("material") or "").strip()
    else:
        zona = (request.args.get("zona") or "").strip()
        material = (request.args.get("material") or "").strip()

    if not zona or not material:
        return (
            jsonify(
                {
                    "erro": "Informe zona e material (GET ?zona=&material= ou POST JSON).",
                }
            ),
            400,
        )

    try:
        resultado = recomendar_ponto(material, zona, verbose=False)
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

    pontos = [_ponto_para_api(p) for p in resultado]
    markers = _markers_para_mapa(resultado)
    return jsonify(
        {
            "zona": zona,
            "material": material,
            "pontos": pontos,
            "markers": markers,
            "total": len(pontos),
        }
    )


@app.route("/", methods=["GET", "POST"])
def index():
    erro: str | None = None
    resultado: List[Dict[str, Any]] | None = None
    markers: List[Dict[str, Any]] = []
    regioes: List[str] = []
    materiais: List[Dict[str, str]] = []

    try:
        regioes = listar_regioes_do_banco()
        materiais = _materiais_lista()
    except Exception as e:
        erro = f"Erro ao acessar o banco: {e}"
        return render_template(
            "index.html",
            erro=erro,
            regioes=[],
            materiais=[],
            zona_selecionada="",
            material_codigo="",
            resultado=None,
            markers=[],
        )

    zona_selecionada = request.form.get("zona") or request.args.get("zona") or ""
    material_codigo = request.form.get("material") or request.args.get("material") or ""

    if not zona_selecionada and regioes:
        zona_selecionada = regioes[0]
    if not material_codigo and materiais:
        material_codigo = materiais[0]["codigo"]

    if request.method == "POST":
        if not material_codigo:
            erro = "Selecione um tipo de resíduo."
        elif not zona_selecionada:
            erro = "Selecione sua região."
        else:
            resultado = recomendar_ponto(
                material_codigo, zona_selecionada, verbose=False
            )
            if not resultado:
                erro = "Nenhum ponto encontrado para este material nesta busca."
            else:
                markers = _markers_para_mapa(resultado)

    return render_template(
        "index.html",
        erro=erro,
        regioes=regioes,
        materiais=materiais,
        zona_selecionada=zona_selecionada,
        material_codigo=material_codigo,
        resultado=resultado,
        markers=markers,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    host = os.environ.get("FLASK_RUN_HOST", "127.0.0.1")
    debug = os.environ.get("FLASK_DEBUG", "true").lower() in ("1", "true", "yes")
    app.run(host=host, port=port, debug=debug)
