"""
This file enables using Ibis expressions inside Altair charts.

To use it, import it and enable the `ibis` renderer adn `ibis` data transformer,
then pass an Ibis expression directly to `altair.Chart`.
"""
import typing
import pprint

import ibis
import ibis.client

import altair
import pandas
from altair.vegalite.v2.display import default_renderer

__all__ = ["display_chart"]

import ipykernel.comm
from IPython.display import JSON, DisplayObject, display, Code, HTML


# Data transformer to use in ibis renderer
DEFAULT_TRANSFORMER = altair.utils.data.to_json


# A placeholder vega spec that will be replaced once the
# transform has been completed and returned via the comm channel.
EMPTY_SPEC = {"data": {"values": []}, "mark": "bar"}

# A comm id used to establish a link between python code
# and frontend vega-lite transforms.
COMM_ID = "extract-vega-lite"


def ibis_renderer(spec, type="vl", extract=True, compile=True):
    """
    Altair renderer for Ibis expressions.

    Arguments:

        type:  What the mimetype of the output should be. Valid types:
            'vl': Vega Lite mimetype so the chart is rendered in the browser.
            'vl-omnisci': OmniSci Vega Lite mimetype so the chart is rendered with the OmniSci Vega renderer
            'json': JSON mimetype so you can see the JSON of the chart.
            'sql': Text mimetype to see the SQL computed for the chart.

        extract: Whether to extract the transformations from the Vega Lite spec. If True, the display for
                 this cell becomes asyncronous, because it has to query the frontend through a comm for the
                 updated spec.
        compile: Whether to take the list of transformations on the spec and compile them to Ibis.
    """
    expr: ibis.Expr = retrieve_expr(spec)
    assert type in ("vl", "vl-omnisci", "json", "sql")
    if type == "vl":
        display_type = VegaLite
        display_data = EMPTY_SPEC
    elif type == "vl-omnisci":
        conn = get_client(expr)
        display_type = VegaLiteOmniSci
        display_data = [EMPTY_SPEC, conn]
    elif type == "json":
        display_type = CompatJSON
        display_data = {"_": "Waiting for transformed spec..."}
    elif type == "sql":
        display_type = Code
        display_data = "Waiting for transformed spec..."

    def to_data(spec, expr=expr):
        # if we should compile the expression, replace it with the updated
        # version and mutate the spec
        if compile:
            expr = update_spec(expr, spec)

        if type == "vl":
            set_data(spec, DEFAULT_TRANSFORMER(expr.execute()))
            return spec
        elif type == "vl-omnisci":
            set_data(spec, {"sql": expr.compile()})
            return [spec, conn]
        elif type == "json":
            return spec
        elif type == "sql":
            return expr.compile()

    def to_display(spec) -> DisplayObject:
        return display_type(to_data(spec))

    if extract:
        display_id = display(display_type(display_data), display_id=True)

        extract_spec(spec, lambda s: display_id.update(to_display(s)))
        return {"text/plain": ""}
    return get_ipython().display_formatter.format(to_display(spec))[0]


##
# Custom display objects
##


class VegaLiteOmniSci(DisplayObject):
    def _repr_mimebundle_(self, include, exclude):
        spec, conn = self.data
        return {
            "application/vnd.omnisci.vega+json": {
                "vegalite": spec,
                "connection": {
                    "host": conn.host,
                    "protocol": conn.protocol,
                    "port": conn.port,
                    "user": conn.user,
                    "dbname": conn.db_name,
                    "password": conn.password,
                },
            }
        }


class VegaLite(DisplayObject):
    def _repr_mimebundle_(self, include, exclude):
        return default_renderer(self.data)


class CompatJSON(JSON):
    def _repr_html_(self):
        return "<pre>" + pprint.pformat(self.data, width=120) + "</pre>"

##
# Utils
##


def extract_spec(spec, callback):
    """
    Calls extract_transform on the frontend and calls the callback with the transformed spec.
    """
    my_comm = ipykernel.comm.Comm(target_name=COMM_ID, data=spec)

    @my_comm.on_msg
    def _recv(msg):
        callback(msg["content"]["data"])


def empty(expr: ibis.Expr) -> pandas.DataFrame:
    """
    Creates an empty DF for a ibis expression, based on the schema

    https://github.com/ibis-project/ibis/issues/1676#issuecomment-441472528
    """
    return expr.schema().apply_to(pandas.DataFrame(columns=expr.columns))


def get_client(expr: ibis.Expr) -> ibis.client.Client:
    return expr.op().table.op().source


def monkeypatch_altair():
    """
    Needed until https://github.com/altair-viz/altair/issues/843 is fixed to let Altair
    handle ibis inputs
    """
    original_chart_init = altair.Chart.__init__

    def updated_chart_init(self, data=None, *args, **kwargs):
        """
        If user passes in a Ibis expression, create an empty dataframe with
        those types and set the `ibis` attribute to the original ibis expression.
        """
        if data is not None and isinstance(data, ibis.Expr):
            expr = data
            data = empty(expr)
            data.ibis = expr

        return original_chart_init(self, data=data, *args, **kwargs)

    altair.Chart.__init__ = updated_chart_init


_i = 0
_name_to_ibis: typing.Dict[str, ibis.Expr] = {}


def retrieve_expr(spec) -> ibis.Expr:
    """
    Given a spec, return the ibis expression associated with it.

    The `data.name` should be a UUID that we look up in our global mapping of names
    to ibis expressions.
    """
    # some specs have sub `spec` key
    if "spec" in spec:
        spec = spec["spec"]
    try:
        return _name_to_ibis.pop(spec["data"]["name"])
    except KeyError:
        raise RuntimeError(
            "Could not find Ibis expression for chart. Make sure Ibis data transformer is enabled: altair.data_transformers.enable('ibis')"
        )


def ibis_transformation(data):
    """
    turn a pandas DF with the Ibis query that made it attached to it into
    a valid Vega Lite data dict. Since this has to be JSON serializiable
    (because of how Altair is set up), we create a unique name and
    save the ibis expression globally with that name so we can pick it up later.
    """
    assert isinstance(data, pandas.DataFrame)
    global _i
    name = f"ibis_{_i}"
    _i += 1
    _name_to_ibis[name] = data.ibis
    return {"name": name}


def translate_op(op: str) -> str:
    return {"mean": "mean", "average": "mean"}.get(op, op)


def vl_aggregate_to_grouping_expr(expr: ibis.Expr, a: dict) -> ibis.Expr:
    if "field" in a:
        expr = expr[a["field"]]
    op = translate_op(a["op"])
    expr = getattr(expr, op)()
    return expr.name(a["as"])


def update_spec(expr: ibis.Expr, spec: dict):
    """
    Takes in an ibis expression and a spec, updating the spec and returning a new ibis expr
    """
    original_expr = expr

    # iterate through transforms and move as many as we can into the ibis expression
    # logic modified from
    # https://github.com/vega/vega-lite-transforms2sql/blob/3b360144305a6cec79792036049e8a920e4d2c9e/transforms2sql.ts#L7
    for transform in spec.get("transform", []):
        groupby = transform.pop("groupby", None)
        if groupby:
            all_fields_exist = all([field in expr.columns for field in groupby])
            if not all_fields_exist:
                transform['groupby'] = groupby
                # we referenced a field that isnt in the expression because it was an aggregate we coudnt process
                continue
            expr = expr.groupby(groupby)

        aggregate = transform.pop("aggregate", None)
        if aggregate:
                expr = expr.aggregate(
                    [vl_aggregate_to_grouping_expr(original_expr, a) for a in aggregate]
                )

        filter_ = transform.pop("filter", None)
        if filter_:
            # https://vega.github.io/vega-lite/docs/filter.html#field-predicate
            field = filter_['field']
            field_expr = original_expr[field]
            if 'range' in filter_:
                min, max = filter_['range']
                preds = [field_expr >= min, field_expr <= max]
            elif 'equal' in filter_:
                preds = [field_expr == filter_['equal']]
            elif 'gt' in filter_:
                preds = [field_expr > filter_['gt']]
            elif 'lt' in filter_:
                preds = [field_expr < filter_['lt']]
            elif 'lte' in filter_:
                preds = [field_expr <= filter_['lte']]
            elif 'gte' in filter_:
                preds = [field_expr >= filter_['gte']]
            else:
                # put filter back if we cant transform itt
                transform['filter'] = filter_
                continue
            expr = expr.filter(preds)

    # remove empty transforms
    spec['transform'] = [i for i in spec.get('transform', []) if i]
    # remove key if empty
    if not spec['transform']:
        del spec['transform']

    return expr


def set_data(spec, data):
    """
    Sets the data on the spec to be the new data
    """
    if "spec" in spec:
        spec["spec"]["data"] = data
    else:
        spec["data"] = data


altair.renderers.register("ibis", ibis_renderer)
altair.data_transformers.register("ibis", ibis_transformation)
monkeypatch_altair()


def display_chart(chart: altair.Chart, backend_render=False) -> None:
    """
    Given an Altair chart created around an Ibis expression, this displays the different
    stages of rendering of that chart. Helpful for debugging.

    backend_render: Whether to also render with OmniSci's builtin Vega rendering.
    """

    def display_header(name):
        display(HTML(f"<h3>{name}</h3>"))

    def display_render(compile, extract, type):
        altair.renderers.enable("ibis", compile=compile, extract=extract, type=type)
        method = f'altair.renderers.enable("ibis", compile={compile}, extract={extract}, type={repr(type)})'
        display(HTML(f"<strong><code>{method}</code></strong>"))
        display(chart)

    display_header("Initial")
    display_render(False, False, "json")
    display_render(False, False, "sql")
    display_render(False, False, "vl")
    if backend_render:
        display_render(False, False, "vl-omnisci")

    display_header("Compiled")
    display_render(True, False, "json")
    display_render(True, False, "sql")
    display_render(True, False, "vl")
    if backend_render:
        display_render(False, False, "vl-omnisci")

    display_header("Extracted")
    display_render(False, True, "json")
    display_render(False, True, "vl")

    display_header("Extracted then Compiled")
    display_render(True, True, "json")
    display_render(True, True, "sql")
    display_render(True, True, "vl")
    if backend_render:
        display_render(False, False, "vl-omnisci")