# AP Hub Location - Streamlit

Interface Streamlit para executar a ferramenta AP Hub Location.

Esta pasta contem o minimo necessario para funcionar: app, modelos, utilidades e
instancias AP.

## Como executar

Entre na pasta:

```powershell
cd "C:\Users\laura\OneDrive\Área de Trabalho\IC - Luiza\New Project"
```

Rode usando o ambiente virtual da pasta anterior:

```powershell
..\.venv\Scripts\python.exe -m streamlit run app_streamlit.py
```

Se o ambiente virtual estiver ativado:

```powershell
streamlit run app_streamlit.py
```

A pagina usa as instancias em `data/APdata` e salva as figuras em `outputs`.
