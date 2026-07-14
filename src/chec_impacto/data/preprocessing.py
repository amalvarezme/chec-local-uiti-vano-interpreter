from __future__ import annotations

import warnings
import re
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, MinMaxScaler

# ==========================================
# 2. Configuración Inicial
# ==========================================
# Supresión de warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="pandas")
warnings.filterwarnings("ignore", category=FutureWarning)

def procesar_dataset_completo(
    path_clima='data/Indicadores_vano_v3.csv',
    path_variables_seleccion='data/Variables_seleccion.xlsx',
    use_sampling=False,
    min_samples_per_codigo=10,
    seed=42,
    target='UITI_VANO',
    filtro_uiti_max=1000,
    ventana_climatica_horas=12,
):
    """
    Carga datos, filtra, aplica seleccion de variables, imputa y codifica.

    Parámetros:
    -----------
    path_clima : str
        Ruta al archivo de datos (.pkl, .csv, .xlsx).
    path_variables_seleccion : str
        Ruta al Excel con columnas COLUMNA y SELECCIÓN.
    use_sampling : bool
        Si True, realiza muestreo por CODIGO antes del enriquecimiento.
    min_samples_per_codigo : int
        Máximo número de muestras a tomar por cada CODIGO.
    seed : int
        Semilla aleatoria para el muestreo.
    target : str
        Nombre de la columna objetivo. Por defecto 'UITI_VANO'.
    filtro_uiti_max : float o None
        Umbral máximo para filtrar la columna objetivo antes del procesamiento.
        Si es None, no se aplica filtro.
    ventana_climatica_horas : int
        Cantidad de lags horarios climaticos a conservar por prefijo.
        Por defecto 12 conserva las columnas *_0 hasta *_11.

    Retorna:
    --------
    dict
    """

    if ventana_climatica_horas < 1:
        raise ValueError("ventana_climatica_horas debe ser mayor o igual a 1.")

    print("Cargando datos...")
    path_clima = Path(path_clima)
    path_variables_seleccion = Path(path_variables_seleccion)
    if not path_variables_seleccion.exists():
        data_candidate = Path("data") / path_variables_seleccion.name
        if data_candidate.exists():
            path_variables_seleccion = data_candidate

    path_clima_str = str(path_clima)
    if path_clima_str.lower().endswith((".pkl", ".pickle")):
        Xdata = pd.read_pickle(path_clima)
    elif path_clima_str.lower().endswith(".csv"):
        Xdata = pd.read_csv(path_clima)
    elif path_clima_str.lower().endswith((".xlsx", ".xls")):
        Xdata = pd.read_excel(path_clima)
    else:
        raise ValueError("path_clima debe ser .pkl, .csv, .xlsx o .xls.")

    Xdata.reset_index(inplace=True, drop=True)
    if 'FECHA' in Xdata.columns:
        Xdata['FECHA'] = pd.to_datetime(Xdata['FECHA'], errors='coerce')

    if filtro_uiti_max is not None:
        if target not in Xdata.columns:
            raise ValueError(f"La columna objetivo '{target}' no existe en Xdata para aplicar el filtro.")
        Xdata = Xdata[Xdata[target] <= filtro_uiti_max].copy()

    if use_sampling:
        if 'CODIGO' not in Xdata.columns:
            raise ValueError("La columna 'CODIGO' no existe en Xdata para realizar el muestreo.")

        def sample_group(g):
            n = len(g)
            return g.sample(
                n=min(n, min_samples_per_codigo),
                random_state=seed
            )

        Xdata = (
            Xdata.groupby("CODIGO", group_keys=False)
                 .apply(sample_group)
                 .copy()
        )
        Xdata.reset_index(drop=True, inplace=True)

    seleccion = pd.read_excel(path_variables_seleccion)
    required_selection_cols = {'COLUMNA', 'SELECCIÓN'}
    missing_selection_cols = required_selection_cols - set(seleccion.columns)
    if missing_selection_cols:
        raise ValueError(
            f"El archivo de variables debe tener las columnas {required_selection_cols}. "
            f"Faltan: {sorted(missing_selection_cols)}"
        )

    max_lag_to_keep = ventana_climatica_horas - 1

    # Validación target
    if target not in Xdata.columns:
        raise ValueError(f"La columna objetivo '{target}' no existe en Xdata.")

    seleccion['COLUMNA'] = seleccion['COLUMNA'].astype(str).str.strip()
    seleccion['SELECCIÓN'] = pd.to_numeric(seleccion['SELECCIÓN'], errors='coerce').fillna(0)
    selected_variables = seleccion.loc[seleccion['SELECCIÓN'].eq(1), 'COLUMNA'].tolist()

    lagged_prefixes = {
        match.group(1)
        for col in Xdata.columns
        if (match := re.match(r"^(.+)_(\d+)$", str(col)))
    }

    selected_columns = []
    missing_selected_variables = []
    for variable in selected_variables:
        if variable == target:
            continue

        if variable in lagged_prefixes:
            climate_cols = []
            for col in Xdata.columns:
                match = re.match(rf"^{re.escape(variable)}_(\d+)$", str(col))
                if match and int(match.group(1)) <= max_lag_to_keep:
                    climate_cols.append(col)
            climate_cols.sort(key=lambda col: int(str(col).rsplit("_", 1)[1]))
            if climate_cols:
                selected_columns.extend(climate_cols)
            else:
                missing_selected_variables.append(variable)
        elif variable in Xdata.columns:
            selected_columns.append(variable)
        else:
            missing_selected_variables.append(variable)

    selected_columns = list(dict.fromkeys(selected_columns))
    if missing_selected_variables:
        raise ValueError(
            "Estas variables seleccionadas no existen en el dataset ni como prefijo climatico: "
            f"{missing_selected_variables}"
        )

    # Copia enriquecida final
    #Dur_h = Xdata['DURACION'].values if 'DURACION' in Xdata.columns else None
    df1 = Xdata.copy()

    # Separación de target
    y = Xdata[[target]].values.astype('float32')

    # Construcción de variables predictoras
    Xdata_model = Xdata[selected_columns].copy()

    df = Xdata_model.copy()

    # Conversión de fechas restantes a timestamp
    DATE_COLUMNS = df.select_dtypes(include=['datetime64[ns]']).columns.tolist()
    for col in DATE_COLUMNS:
        df[col] = df[col].astype(np.int64) // 10**9
        df[col] = df[col].astype('float32')

    # Imputación numérica
    NUMERIC_COLUMNS = df.select_dtypes(include=['number']).columns.tolist()
    CATEGORICAL_COLUMNS = df.select_dtypes(include=['object', 'category']).columns.tolist()

    max_values = {}
    for col in NUMERIC_COLUMNS:
        max_val = pd.to_numeric(df[col], errors='coerce').max()
        if pd.isna(max_val):
            max_val = 0.0
        max_values[col] = max_val
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(-10.0 * max_val)

    # Codificación categórica
    label_encoders = {}
    categorical_dims = {}
    for col in CATEGORICAL_COLUMNS:
        enc = LabelEncoder()
        s = df[col].fillna("no aplica").astype(str)
        enc.fit(s)
        df[col] = enc.transform(s)
        label_encoders[col] = enc
        categorical_dims[col] = len(enc.classes_)

    # Matriz final
    features = list(df.columns)
    X = df[features].values.astype('float32')

    print("Procesamiento completado.")
    print(f"Shape X: {X.shape}, Shape y: {y.shape}")

    return {
        "X": X,
        "y": y,
        "features": features,
        "df_final": df,
        "df_original_copy": df1,
        #"duracion_h": Dur_h,
        "label_encoders": label_encoders,
        "categorical_dims": categorical_dims,
        "max_values_imputed": max_values,
        "Xdata": Xdata_model,
        "CATEGORICAL_COLUMNS": CATEGORICAL_COLUMNS
    }

def preparar_splits_estratificados(X, y,
                                   test_size=0.20, valid_size=0.20,
                                   random_state=42,
                                   modo='clasificacion'):
    """
    Prepara splits Train/Valid/Test estratificados para clasificacion.

    Usa MinMaxScaler para calcular percentiles del objetivo y devuelve clases
    ordinales 0, 1, 2, 3 generadas con percentiles 25, 50 y 75.
    """

    modo = modo.lower()
    if modo != 'clasificacion':
        raise ValueError("modo debe ser 'clasificacion'.")

    y = np.asarray(y)
    if y.ndim == 1:
        y = y.reshape(-1, 1)

    scaler = MinMaxScaler()
    y_scaled = scaler.fit_transform(y)

    percentiles = np.percentile(y_scaled[:, 0], [25, 50, 75])
    y_categorized = np.digitize(
        y_scaled[:, 0].flatten(),
        bins=percentiles
    ).astype(int)

    objetivo_split = y_categorized.reshape(-1, 1)

    X_temp, X_test, y_temp, y_test, ycat_temp, ycat_test = train_test_split(
        X,
        objetivo_split,
        y_categorized,
        test_size=test_size,
        random_state=random_state,
        stratify=y_categorized
    )

    estratificacion_validacion = ycat_temp

    X_train, X_valid, y_train, y_valid, ycat_train, ycat_valid = train_test_split(
        X_temp,
        y_temp,
        ycat_temp,
        test_size=valid_size,
        random_state=random_state,
        stratify=estratificacion_validacion
    )

    print(f"Dataset original: X={X.shape}, y={y.shape}")
    print(f"Splits generados -> Train: {X_train.shape}, Valid: {X_valid.shape}, Test: {X_test.shape}")
    print(f"Modo objetivo: {modo}")
    print("\nDistribución de clases para estratificación:")
    print("Original:", np.bincount(y_categorized))
    print("Train:   ", np.bincount(ycat_train))
    print("Valid:   ", np.bincount(ycat_valid))
    print("Test:    ", np.bincount(ycat_test))

    return {
        "X_train": X_train,
        "X_valid": X_valid,
        "X_test": X_test,
        "y_train": y_train,
        "y_valid": y_valid,
        "y_test": y_test,
        "scaler": scaler,
        "y_categories_original": y_categorized,
        "y_scaled": y_scaled,
        "modo": modo
    }


