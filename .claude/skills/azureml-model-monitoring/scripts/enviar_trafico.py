# /// script
# requires-python = ">=3.10"
# dependencies = ["pandas", "requests"]
# ///
"""
Envia trafico al endpoint del modelo Voting Ensemble (plan de salud) para que
la data collection guarde datos de produccion y Model Monitoring tenga que comparar.

Dos modos:
  normal -> filas reales de insurance.csv (se parecen al entrenamiento)
  drift  -> las mismas filas alteradas a proposito: mas edad, mas BMI,
            mas fumadores y todos de una region. El monitor deberia alertar.

La URL y la key se obtienen con az CLI en tiempo de ejecucion: no se guardan
en ningun archivo ni se imprimen.

Uso:
  uv run enviar_trafico.py --modo normal --filas 400
  uv run enviar_trafico.py --modo drift  --filas 400
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import requests

RESOURCE_GROUP = "datapath-mlops18-kaic"
WORKSPACE = "ws-datapath-mlops18-kaic"
ENDPOINT = "endpoint-voting-ensemble-mlops"
DEPLOYMENT = "modelo-voting-ensemble-mlops18"
CSV = Path(__file__).parent / "datos" / "insurance.csv"
COLUMNAS_MODELO = ["age", "sex", "bmi", "children", "smoker", "region"]
TAMANO_LOTE = 50


def az(*args: str) -> str:
    """Ejecuta az CLI y devuelve stdout sin saltos de linea."""
    salida = subprocess.run(
        ["az", *args, "-g", RESOURCE_GROUP, "-w", WORKSPACE, "-o", "tsv"],
        capture_output=True, text=True, check=True,
    )
    return salida.stdout.strip()


def aplicar_drift(df: pd.DataFrame) -> pd.DataFrame:
    """Altera la distribucion de las features para provocar data drift."""
    df = df.copy()
    df["age"] = (df["age"] + 15).clip(upper=80)
    df["bmi"] = (df["bmi"] * 1.25).round(2)
    df["smoker"] = df["smoker"].where(df.index % 10 >= 7, "yes")  # ~70% fumadores
    df["region"] = "northeast"
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--modo", choices=["normal", "drift"], required=True)
    parser.add_argument("--filas", type=int, default=400)
    args = parser.parse_args()

    url = az("ml", "online-endpoint", "show", "-n", ENDPOINT, "--query", "scoring_uri")
    key = az("ml", "online-endpoint", "get-credentials", "-n", ENDPOINT, "--query", "primaryKey")

    df = pd.read_csv(CSV)[COLUMNAS_MODELO].sample(n=args.filas, replace=args.filas > 1338, random_state=None)
    df = df.reset_index(drop=True)
    if args.modo == "drift":
        df = aplicar_drift(df)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "azureml-model-deployment": DEPLOYMENT,
    }

    ok, errores = 0, 0
    for inicio in range(0, len(df), TAMANO_LOTE):
        lote = df.iloc[inicio:inicio + TAMANO_LOTE]
        cuerpo = {"input_data": json.loads(lote.to_json(orient="split", index=True))}
        r = requests.post(url, headers=headers, json=cuerpo, timeout=60)
        if r.ok:
            ok += len(lote)
        else:
            errores += len(lote)
            print(f"  lote {inicio}: HTTP {r.status_code} {r.text[:200]}", file=sys.stderr)
        time.sleep(0.5)

    print(f"Modo {args.modo}: {ok} filas puntuadas, {errores} con error.")
    if ok:
        print("Ejemplo de prediccion (charges):", requests.post(
            url, headers=headers, timeout=60,
            json={"input_data": json.loads(df.head(1).to_json(orient="split", index=True))},
        ).text[:200])


if __name__ == "__main__":
    main()
