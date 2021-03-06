import numpy as np

import xarray as xr
import xarray.ufuncs as xu


def all_combos(elements, max_n):
    """ Given a list `elements` of $n$ values, return a generator which
    will yield all subsets of 1, 2, ..., `max_n` combinations from that
    list.

    """
    return chain(*[combinations(elements, i) for i in range(1, 1 + max_n)])


def area_grid(lon, lat, asarray=False):
    """ Compute the area of the grid specified by 1D arrays
    lon and lat. Returns the result as a 2D array (nlon, nlat)
    containing the area of each gridbox, in m^2.
    Parameters
    ----------
    lon, lat : array-like of floats
        Arrays containing the longitude and latitude values
        of the given grid.
    asarray : Boolean
        Return an array instead of DataArray object
    Returns
    -------
    areas : xarray.DataArray or array
        Array with shape (len(lon), len(lats)) containing the
        area (in m^2) of each cell on the grid.
    """

    #: Earth's radius (m)
    R_EARTH = 6375000.

    # Induce lon/lat to array-like
    lon_arr = np.asarray(lon)
    lat_arr = np.asarray(lat)

    ## grid parameters
    nlon, nlat = len(lon_arr), len(lat_arr)
    # mean delta lon between gridpoints (actually constant on regular grid)
    # converted to radians
    dlon  = np.abs(np.mean(lon_arr[1:]-lon_arr[:-1]))*np.pi/180.
    # same, for lat
    dlat  = np.abs(np.mean(lat_arr[1:]-lat_arr[:-1]))*np.pi/180.
    # convert latitudes from -90,90 -> -180, 0 and then to radians
    theta = (90. - lat_arr)*np.pi/180.

    areas = np.zeros([nlon, nlat])
    for lat_i in range(nlat):
        for lon_i in range(nlon):

            lat1 = theta[lat_i] - dlat/2.
            lat2 = theta[lat_i] + dlat/2.

            if (theta[lat_i] == 0) or (theta[lat_i] == np.pi):
                areas[lon_i, lat_i] = (R_EARTH**2.) \
                                     *np.abs(  np.cos(dlat/2.) \
                                             - np.cos(0.)     )*dlon
            else:
                areas[lon_i, lat_i] = (R_EARTH**2.) \
                                     *np.abs( np.cos(lat1) - np.cos(lat2) )*dlon

    areas = areas.T # re-order (lat, lon)

    if asarray:
        return areas
    else:
        # Construct DataArray from the result

        # For some reason, there are random issues with the order
        # of the coordinates, so we try both ways here.
        coords = [lon, lat]
        dims = ['lon', 'lat']
        while True:
            try:
                areas = DataArray(
                    areas, coords=coords, dims=dims, name='area',
                    attrs=dict(long_name="grid cell area", units="m^2")
                )

                break
            except ValueError:
                areas = areas.T

        return areas


def clean_xy(x, y):
    """ Given two arrays of paired observations, drop indices where one or
    both of the observations are NaN. """
    df = pd.DataFrame({"x": x, "y": y}).dropna()
    return df.x.values, df.y.values


def detrend_moving_avg(ds, n_years=5, dim="time", center=True, min_periods=1):
    """ Detrend a dataset by computing a 5-year moving average centered on
    each month for each monthly timeseries. Assume that we have monthly
    data to begin with. """

    means = ds.mean(dim)
    moving_avg = ds.rolling(
        center=center, min_periods=min_periods, **{dim: n_years}
    )
    detrended = ds - moving_avg.mean()  # + means
    return detrended


def find_nearest(array, value):
    """ Find the index of the nearest element in `array` to `value`. """
    idx = (np.abs(array - value)).argmin()
    return idx


def global_avg(data, weights=None, dims=['lon', 'lat']):
    """ Compute (area-weighted) global average over a DataArray
    or Dataset. If `weights` are not passed, they will be computed
    by using the areas of each grid cell in the dataset.
    .. note::
        Handles missing values (nans and infs).
    """

    if isinstance(data, xr.DataArray):

        if weights is None:  # Compute gaussian weights in latitude
            weights = area_grid(data.lon, data.lat)
            # Saving for later - compute latitudinal weighting
            # gw = weights.sum('lon')
            # weights = 2.*gw/gw.sum('lat')

        weights = weights.where(xu.isfinite(data))
        total_weights = weights.sum(dims)

        return (data*weights).sum(dims)/total_weights

    elif isinstance(data, xr.Dataset):

        # Create a new temporary Dataset
        new_data = xr.Dataset()

        # Iterate over the contents of the original Dataset,
        # which are all DataArrays, and compute the global avg
        # on those elements.
        for v in data.data_vars:
            coords = data[v].coords
            if not ('lon' in coords):
                new_data[v] = data[v]
            else:
                new_data[v] = global_avg(data[v], weights)

        # Collapse remaining lat, lon dimensions if they're here
        leftover_dims = [d for d in dims if d in new_data.coords]
        if leftover_dims:
            new_data = new_data.sum(leftover_dims)
        return new_data


def great_circle_dist(lon1, lat1, lon2, lat2, r=1.0):
    """ Compute great-circle distance between (lat, lon)
    coordinates on a sphere).

    Uses a special case of the Vincenty formula assuming
    ellipsoid has equal major/minor axes; see
    https://en.wikipedia.org/wiki/Great-circle_distance
    for more information.

    Parameters
    ----------
    lon1, lat1, lon2, lat2 : float or array of floats
        Longitudes/Latitudes, given in degrees.
    r : float (default=1.0)
        Scaling factor


    Returns
    -------
    great circle distance in degrees, or scaled by factor 'r'
    """

    # Convert to radians
    lat1, lat2 = (
        np.asarray(lat1) * np.pi / 180.0,
        np.asarray(lat2) * np.pi / 180.0,
    )
    dlon = (lon1 - lon2) * np.pi / 180.0

    # Cache trig values of coordinates
    c1, s1 = np.cos(lat1), np.sin(lat1)
    c2, s2 = np.cos(lat2), np.sin(lat2)
    cd = np.cos(dlon)
    sd = np.sin(dlon)

    # Apply Vincenty formula and return
    return (
        r
        * (180.0 / np.pi)
        * np.arctan2(
            np.sqrt((c2 * sd) ** 2 + (c1 * s2 - s1 * c2 * cd) ** 2),
            s1 * s2 + c1 * c2 * cd,
        )
    )


def isin(da, vals):
    """ Determine whether or not values in a given DataArray belong
    to a set of permissible values. """
    return da.to_series().isin(vals).to_xarray()


def logger(func):
    """ Print a function's class/name to console before  entering. """

    @wraps(func)
    def with_logging(*args, **kwargs):
        print("{}.{}".format(args[0].__class__.__name__, func.__name__))
        return func(*args, **kwargs)

    return with_logging


def months_surrounding(month, width=1):
    """ Create a tuple with the ordinal of the given month and the ones before
    and after it up to a certain width, wrapping around the calendar.

    Parameters
    ----------
    month : int
        Ordinal of month, e.g. July is 7
    width : int
        Amount of buffer months to include on each side

    Examples
    --------

    Grab July with June and August

    >>> _months_surrounding(7, 1)
    (6, 7, 8)

    """

    # Edge case: all months
    if width >= 6:
        return tuple(range(1, 12 + 1))

    lo = month - width
    hi = month + width
    months = []
    for m in range(lo, hi + 1):
        if m < 1:
            m += 12
        elif m > 12:
            m -= 12
        months.append(m)
    return tuple(months)


def poor_isin(arr, vals, op="or"):
    """ This is a hack to check if the values in a given array 'arr' are contained
    in a reference list of values 'vals'. To do this, we simply compute a
    vectorized equality comparison for each element in the list and combine
    them using a bitwise 'or' or 'and', depending on which op is specified by the
    user. A proper "isin" calculation will use the 'or' operator.

    """
    if op not in ["and", "or"]:
        raise ValueError("Unknown op '{}'".format(op))

    mask = np.ones_like(arr) if op == "and" else np.zeros_like(arr)
    for val in vals:
        if op == "and":
            mask = mask & (arr == val)
        elif op == "or":
            mask = mask | (arr == val)
    return mask


def shift_lons(ds, lon_dim="lon", neg_dateline=True):
    """ Shift longitudes from [0, 360] to [-180, 180]

    If `neg_dateline` is True (by default), then a longitude of 180 deg
    stays the same; else it is converted to -180 deg (180 W).

    """
    ds_copy = ds.copy()

    lons = ds_copy[lon_dim].values
    new_lons = np.empty_like(lons)
    if neg_dateline:
        mask = lons >= 180
    else:
        mask = lons > 180

    new_lons[mask] = -(360.0 - lons[mask])
    new_lons[~mask] = lons[~mask]

    ds_copy[lon_dim].values = new_lons

    return ds_copy


def shift_roll(data, dim="lon"):
    """ Shift longitude values in a Dataset or DataArray from [0, 360] to
    [-180, 180] and then roll the longitude dimension so that it is ordered
    and monotonic.

    """
    return shift_lons(data).roll(lon=len(data[dim]) // 2 - 1)


def stack_fields(ds, fields, reshape=True):
    """ Given a Dataset and a set of field variables, stack the data
    into a 2D array with the shape (p, f) where "p" is the total number of
    lat-lon grid cells in the data and "f" is the number of fields.

    Parameters
    ----------
    ds : Dataset
        Dataset containing the indicated "fields." Each field must have the
        same dimensions, and must be 2D (lat, lon).
    fields : list of str
        List of strings indicating field names to use in stacking the data
    reshape : bool
        Reshape the data after the fact; if the data has already been 'stacked'
        then this would be superfluous.

    Returns
    -------
    M : 2D array-like
        Shape (p, f) array with the requested field data unraveled and stacked

    """

    M = []
    for field in fields:
        row = ds[field].data
        M.append(row)
    M = np.stack(M, axis=-1)

    if reshape:
        nlon, nlat, nv = M.shape
        M = M.reshape([nlon * nlat, nv])

    # Mask NaNs w/ 0's
    M[np.isnan(M)] = 0.0

    return M
