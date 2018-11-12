# jupyterlab-omnisci

Connect to OmniSci, query their databases, and render the OmniSci-flavored Vega specification,
all within JupyterLab

![example](./screenshot.png)

## Installation

Requirements:

- JupyterLab v0.35
- Access to an OmniSci Immerse server

To install the `jupyterlab-omnisci` extension, run the following in a terminal:

```bash
jupyter labextension install jupyterlab-omnisci
```

## Installing from source

To install from source, run the following in a terminal:

```bash
git clone https://github.com/Quansight/jupyterlab-omnisci
cd jupyterlab-omnisci
jlpm install
jlpm run build
jupyter labextension install .
```

## Edit the default database connection

In JupyterLab, click **Settings > Advanced Settings** to modify the default database connections.

![](https://user-images.githubusercontent.com/4236275/39148358-1cd0ccb0-470a-11e8-9561-8b1e65b8b906.png)

## Developing with Docker

You can start developing on this locally with Docker

```bash
git clone https://github.com/Quansight/jupyterlab-omnisci
cd jupyterlab-omnisci
docker-compose up
```

Open link to Jupyterlab instance once it is built and shows up in the logs.
The app will be rebuilt when you change the jupyterlab extension. Reload
the page to get the changes.
