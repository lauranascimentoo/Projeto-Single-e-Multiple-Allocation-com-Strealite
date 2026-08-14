# SP Hub Location - Streamlit

Interface Streamlit para resolver o problema de localização de hubs com a
instância de São Paulo.

## Instância

A aplicação lê os arquivos de `data/SPdata`. O formato atual contém:

- quantidade e coordenadas dos nós;
- matriz de demanda;
- matrizes de custo de coleta e entrega;
- parâmetros de demanda, coleta e entrega.

O custo inter-hub é calculado pela aplicação a partir de `c_hub`, `alpha` e da
distância geográfica entre os nós.

## Como executar

Na raiz do projeto, instale as dependências:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Inicie a interface:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app_streamlit.py
```

A aplicação salva figuras em `outputs` e registros de execução em `Logs`.
