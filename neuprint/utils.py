"""
Utility functions for manipulating neuprint-python output.
"""
import sys
import inspect
import functools
from itertools import combinations
from collections import namedtuple
from collections.abc import Iterable, Iterator, Collection

import numpy as np
import pandas as pd
import networkx as nx
from scipy.spatial import cKDTree

#
# Import the notebook-aware version of tqdm if
# we appear to be running within a notebook context.
#
try:
    import ipykernel.iostream
    if isinstance(sys.stdout, ipykernel.iostream.OutStream):
        from tqdm.notebook import tqdm
    else:
        from tqdm import tqdm
except ImportError:
    from tqdm import tqdm


class tqdm(tqdm):
    """
    Same as tqdm, but auto-disable the progress bar if there's only one item.
    """
    def __init__(self, iterable=None, *args, disable=None, **kwargs):
        if disable is None:
            disable = (iterable is not None
                       and hasattr(iterable, '__len__')
                       and len(iterable) <= 1)
        
        super().__init__(iterable, *args, disable=disable, **kwargs)


def trange(*args, **kwargs):
    return tqdm(range(*args), **kwargs)


def make_iterable(x):
    """
    If ``x`` is already a list or array, return it unchanged.
    If ``x`` is Series, return its values.
    If ``x`` is ``None``, return an empty list ``[]``.
    Otherwise, wrap it in a list.
    """
    if x is None:
        return []
    
    if isinstance(x, np.ndarray):
        return x
    
    if isinstance(x, pd.Series):
        return x.values
    
    if isinstance(x, Collection) and not isinstance(x, str):
        return x
    else:
        return [x]


def make_args_iterable(argnames):
    """
    Returns a decorator.
    For the given argument names, the decorator converts the
    arguments into iterables via ``make_iterable()``.
    """
    def decorator(f):

        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            callargs = inspect.getcallargs(f, *args, **kwargs)
            for name in argnames:
                callargs[name] = make_iterable(callargs[name])
            return f(**callargs)

        wrapper.__signature__ = inspect.signature(f)
        return wrapper

    return decorator


@make_args_iterable(['properties'])
def merge_neuron_properties(neuron_df, conn_df, properties=['type', 'instance']):
    """
    Merge neuron properties to a connection table.
    
    Given a table of neuron properties and a connection table, append
    ``_pre`` and ``_post`` columns to the connection table for each of
    the given properties via the appropriate merge operations.
    
    Args:
        neuron_df:
            DataFrame with columns for 'bodyId' and any properties you want to merge
        
        conn_df:
            DataFrame with columns ``bodyId_pre`` and ``bodyId_post``
        
        properties:
            Column names from ``neuron_df`` to merge onto ``conn_df``.
    
    Returns:
        Updated ``conn_df`` with new columns.
    
    Example:
    
        .. code-block:: ipython
    
            In [1]: from neuprint import fetch_adjacencies, NeuronCriteria as NC, merge_neuron_properties
               ...: neuron_df, conn_df = fetch_adjacencies(rois='PB', min_roi_weight=120)
               ...: print(conn_df)
               bodyId_pre  bodyId_post roi  weight
            0   880875736   1631450739  PB     123
            1   880880259    849421763  PB     141
            2   910442723    849421763  PB     139
            3   910783961   5813070465  PB     184
            4   911129204    724280817  PB     127
            5   911134009    849421763  PB     125
            6   911565419   5813070465  PB     141
            7   911911004   1062526223  PB     125
            8   911919044    973566036  PB     122
            9  5813080838    974239375  PB     136
            
            In [2]: merge_neuron_properties(neuron_df, conn_df, 'type')
            Out[2]:
               bodyId_pre  bodyId_post roi  weight  type_pre    type_post
            0   880875736   1631450739  PB     123  Delta7_a  PEN_b(PEN2)
            1   880880259    849421763  PB     141  Delta7_a  PEN_b(PEN2)
            2   910442723    849421763  PB     139  Delta7_a  PEN_b(PEN2)
            3   910783961   5813070465  PB     184  Delta7_a  PEN_b(PEN2)
            4   911129204    724280817  PB     127  Delta7_a  PEN_b(PEN2)
            5   911134009    849421763  PB     125  Delta7_a  PEN_b(PEN2)
            6   911565419   5813070465  PB     141  Delta7_a  PEN_b(PEN2)
            7   911911004   1062526223  PB     125  Delta7_b  PEN_b(PEN2)
            8   911919044    973566036  PB     122  Delta7_a  PEN_b(PEN2)
            9  5813080838    974239375  PB     136       EPG          PEG
    """
    neuron_df = neuron_df[['bodyId', *properties]]
    
    newcols  = [f'{prop}_pre'  for prop in properties]
    newcols += [f'{prop}_post' for prop in properties]    
    conn_df = conn_df.drop(columns=newcols, errors='ignore')

    conn_df = conn_df.merge(neuron_df, 'left', left_on='bodyId_pre', right_on='bodyId')
    del conn_df['bodyId']

    conn_df = conn_df.merge(neuron_df, 'left', left_on='bodyId_post', right_on='bodyId',
                            suffixes=['_pre', '_post'])
    del conn_df['bodyId']

    return conn_df


def connection_table_to_matrix(conn_df, group_cols='bodyId', weight_col='weight', sort_by=None):
    """
    Given a weighted connection table, produce a weighted adjacency matrix.
    
    Args:
        conn_df:
            A DataFrame with columns for pre- and post- identifiers
            (e.g. bodyId, type or instance), and a column for the
            weight of the connection.
        
        group_cols:
            Which two columns to use as the row index and column index
            of the returned matrix, respetively.
            Or give a single string (e.g. ``"body"``, in which case the
            two column names are chosen by appending the suffixes
            ``_pre`` and ``_post`` to your string.

            If a pair of pre/post values occurs more than once in the
            connection table, all of its weights will be summed in the
            output matrix.
        
        weight_col:
            Which column holds the connection weight, to be aggregated for each unique pre/post pair.
            
        sort_by:
            How to sort the rows and columns of the result.
            Can be two strings, e.g. ``("type_pre", "type_post")``,
            or a single string, e.g. ``"type"`` in which case the suffixes are assumed.
            
    Returns:
        DataFrame, shape NxM, where N is the number of unique values in
        the 'pre' group column, and M is the number of unique values in
        the 'post' group column.
    
    Example:
    
        .. code-block:: ipython
        
            In [1]: from neuprint import fetch_simple_connections, NeuronCriteria as NC  
               ...: kc_criteria = NC(type='KC.*', regex=True)
               ...: conn_df = fetch_simple_connections(kc_criteria, kc_criteria)
            In [1]: conn_df.head()
            Out[1]:
               bodyId_pre  bodyId_post  weight type_pre type_post instance_pre instance_post                                       conn_roiInfo
            0  1224137495   5813032771      29      KCg       KCg          KCg    KCg(super)  {'MB(R)': {'pre': 26, 'post': 26}, 'gL(R)': {'...
            1  1172713521   5813067826      27      KCg       KCg   KCg(super)         KCg-d  {'MB(R)': {'pre': 26, 'post': 26}, 'PED(R)': {...
            2   517858947   5813032943      26   KCab-p    KCab-p       KCab-p        KCab-p  {'MB(R)': {'pre': 25, 'post': 25}, 'PED(R)': {...
            3   642680826   5812980940      25   KCab-p    KCab-p       KCab-p        KCab-p  {'MB(R)': {'pre': 25, 'post': 25}, 'PED(R)': {...
            4  5813067826   1172713521      24      KCg       KCg        KCg-d    KCg(super)  {'MB(R)': {'pre': 23, 'post': 23}, 'gL(R)': {'...
    
            In [2]: from neuprint.utils import connection_table_to_matrix
               ...: connection_table_to_matrix(conn_df, 'type')
            Out[2]:
            type_post   KC  KCa'b'  KCab-p  KCab-sc     KCg
            type_pre
            KC           3     139       6        5     365
            KCa'b'     154  102337     245      997    1977
            KCab-p       7     310   17899     3029     127
            KCab-sc      4    2591    3975   247038    3419
            KCg        380    1969      79     1526  250351
    """
    if isinstance(group_cols, str):
        group_cols = (f"{group_cols}_pre", f"{group_cols}_post") 
    
    assert len(group_cols) == 2, \
        "Please provide two group_cols (e.g. 'bodyId_pre', 'bodyId_post')"
    
    assert group_cols[0] in conn_df, \
        f"Column missing: {group_cols[0]}"

    assert group_cols[1] in conn_df, \
        f"Column missing: {group_cols[1]}"
        
    assert weight_col in conn_df, \
        f"Column missing: {weight_col}"
    
    col_pre, col_post = group_cols
    dtype = conn_df[weight_col].dtype

    grouped = conn_df.groupby([col_pre, col_post], as_index=False, sort=False)
    agg_weights_df = grouped[weight_col].sum()
    matrix = agg_weights_df.pivot(col_pre, col_post, weight_col)
    matrix = matrix.fillna(0).astype(dtype)
    
    if sort_by:
        if isinstance(sort_by, str):
            sort_by = (f"{sort_by}_pre", f"{sort_by}_post") 

        assert len(sort_by) == 2, \
            "Please provide two sort_by column names (e.g. 'type_pre', 'type_post')"
        
        pre_order = conn_df.sort_values(sort_by[0])[col_pre].unique()
        post_order = conn_df.sort_values(sort_by[1])[col_post].unique()
        matrix = matrix.reindex(index=pre_order, columns=post_order)
    else:
        # No sort: Keep the order as close to the input order as possible.
        pre_order = conn_df[col_pre].unique()
        post_order = conn_df[col_post].unique()
        matrix = matrix.reindex(index=pre_order, columns=post_order)

    return matrix


def iter_batches(it, batch_size):
    """
    Iterator.
    
    Consume the given iterator/iterable in batches and
    yield each batch as a list of items.
    
    The last batch might be smaller than the others,
    if there aren't enough items to fill it.
    
    If the given iterator supports the __len__ method,
    the returned batch iterator will, too.
    """
    if hasattr(it, '__len__'):
        return _iter_batches_with_len(it, batch_size)
    else:
        return _iter_batches(it, batch_size)


class _iter_batches:
    def __init__(self, it, batch_size):
        self.base_iterator = it
        self.batch_size = batch_size
                

    def __iter__(self):
        return self._iter_batches(self.base_iterator, self.batch_size)
    

    def _iter_batches(self, it, batch_size):
        if isinstance(it, (pd.DataFrame, pd.Series)):
            for batch_start in range(0, len(it), batch_size):
                yield it.iloc[batch_start:batch_start+batch_size]
            return
        elif isinstance(it, (list, np.ndarray)):
            for batch_start in range(0, len(it), batch_size):
                yield it[batch_start:batch_start+batch_size]
            return
        else:
            if not isinstance(it, Iterator):
                assert isinstance(it, Iterable)
                it = iter(it)
    
            while True:
                batch = []
                try:
                    for _ in range(batch_size):
                        batch.append(next(it))
                except StopIteration:
                    return
                finally:
                    if batch:
                        yield batch


class _iter_batches_with_len(_iter_batches):
    def __len__(self):
        return int(np.ceil(len(self.base_iterator) / self.batch_size))


def skeleton_df_to_nx(df, with_attributes=True, directed=True):
    """
    Convert a skeleton DataFrame into a ``networkx`` graph.
    
    Args:
        df:
            DataFrame as returned by :py:meth:`.Client.fetch_skeleton()`
        
        with_attributes:
            If True, store node attributes for x, y, z, radius
        
        directed:
            If True, return ``nx.DiGraph``, otherwise ``nx.Graph``.
    
    Returns:
        ``nx.DiGraph`` or ``nx.Graph``
    """
    if directed:
        g = nx.DiGraph()
    else:
        g = nx.Graph()
    
    if with_attributes:
        for row in df.itertuples(index=False):
            g.add_node(row.rowId, x=row.x, y=row.y, z=row.z, radius=row.radius)
            if row.link != -1:
                g.add_edge(row.link, row.rowId)
    else:
        df = df[['rowId', 'link']].sort_values(['rowId', 'link'])
        g.add_nodes_from(df['rowId'].sort_values())
        g.add_edges_from(df.query('link != -1').values)
    return g


def skeleton_df_to_swc(df, export_path=None):
    """
    Convert a skeleton DataFrame into a the text of an SWC file.
    
    Args:
        df:
            DataFrame, as returned by :py:meth:`.Client.fetch_skeleton()`
        
        export_path:
            Optional. Write the SWC file to disk a the given location.
    
    Returns:
        string
    """
    df['node_type'] = 0
    df = df[['rowId', 'node_type', 'x', 'y', 'z', 'radius', 'link']]
    swc = "# "
    swc += df.to_csv(sep=' ', header=True, index=False)
    
    if export_path:
        with open(export_path, 'w') as f:
            f.write(swc)

    return swc

    
def heal_skeleton(skeleton_df):
    """
    Rather than a single tree, skeletons from neuprint sometimes
    consist of multiple fragments, i.e. multiple connected
    components.  That's due to artifacts in the underlying
    segmentation from which the skeletons were generated.
    In such skeletons, there will be multiple 'root' nodes
    (SWC rows where ``link == -1``).
    
    This function 'heals' a fragmented skeleton by joining its 
    fragments into a single tree. The fragments are joined by
    selecting the minimum spanning tree after joining all fragments
    via their pairwise nearest neighbors.
    
    Args:
        skeleton_df:
            DataFrame as returned by :py:meth:`.Client.fetch_skeleton()`
    
    Returns:
        DataFrame, with ``link`` column updated with updated edges.
    """
    skeleton_df = (skeleton_df.sort_values('rowId').reset_index(drop=True))
    g = skeleton_df_to_nx(skeleton_df, False, False)

    # Extract each fragment's rows and construct a KD-Tree
    CC = namedtuple('CC', ['df', 'kd'])
    ccs = []
    for cc in nx.connected_components(g):
        if len(cc) == len(skeleton_df):
            # There's only one component -- no healing necessary
            return skeleton_df
        
        df = skeleton_df.query('rowId in @cc')
        kd = cKDTree(df[[*'xyz']].values)
        ccs.append( CC(df, kd) )

    # Sort from big-to-small, so the calculations below use a
    # KD tree for the larger point set in every fragment pair.
    ccs = sorted(ccs, key=lambda cc: -len(cc.df))
    
    # Intra-fragment edges must stay linked
    nx.set_edge_attributes(g, 0, 'distance')

    # Connect all fragment pairs at their nearest neighbors
    for cc_a, cc_b in combinations(ccs, 2):
        coords_b = cc_b.df[[*'xyz']].values
        distances, indexes = cc_a.kd.query(coords_b)

        index_b = np.argmin(distances)
        index_a = indexes[index_b]
        
        node_a = cc_a.df['rowId'].iloc[index_a]
        node_b = cc_b.df['rowId'].iloc[index_b]
        dist_ab = distances[index_b]
        g.add_edge(node_a, node_b, distance=dist_ab)

    # Compute MST edges
    mst_edges = nx.minimum_spanning_edges(g, weight='distance', data=False)
    mst = nx.Graph()
    mst.add_nodes_from(g)
    mst.add_edges_from(mst_edges)

    root = skeleton_df['rowId'].iloc[0]
    edges = list(nx.dfs_edges(mst, source=root))
    edges = pd.DataFrame(edges, columns=['link', 'rowId']) # parent, child
    edges = edges.set_index('rowId')['link']

    # Replace 'link' (parent) column using MST edges
    skeleton_df['link'] = skeleton_df['rowId'].map(edges).fillna(-1).astype(int)
    assert (skeleton_df['link'] == -1).sum() == 1
    assert skeleton_df['link'].iloc[0] == -1

    return skeleton_df
