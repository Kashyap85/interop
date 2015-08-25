"""Targets view."""
import json
from auvsi_suas.models import GpsPosition, Target, TargetType, Color, Shape, Orientation
from auvsi_suas.views import logger
from auvsi_suas.views.decorators import require_login
from django.http import HttpResponseBadRequest
from django.http import HttpResponseForbidden
from django.http import HttpResponseNotAllowed
from django.http import HttpResponseNotFound
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.generic import View


def normalize_data(data):
    """Convert received target parameters to native Python types.

    Checks whether values are valid and in-range. Skips any non-existent
    fields.

    Args:
        data: JSON-converted dictionary of target parameters

    Returns:
        data dictionary with all present target fields in native types.

    Raises:
        ValueError: Parameter not convertable or out-of-range
    """

    # 'alphanumeric' and 'description' use the empty string instead of None
    if 'alphanumeric' in data and data['alphanumeric'] is None:
        data['alphanumeric'] = ""
    if 'description' in data and data['description'] is None:
        data['description'] = ""

    # Values may be None to clear them or leave them blank.

    # Type is the one exception; it is required and may not be None.
    if 'type' in data:
        try:
            data['type'] = TargetType.lookup(data['type'])
        except KeyError:
            raise ValueError('Unknown target type "%s"; known types %r' %
                             (data['type'], TargetType.names()))

    if 'latitude' in data and data['latitude'] is not None:
        try:
            data['latitude'] = float(data['latitude'])
            if data['latitude'] < -90 or data['latitude'] > 90:
                raise ValueError
        except ValueError:
            # Unable to convert to float or out-of-range
            raise ValueError('Invalid latitude "%s", must be -90 <= lat <= 90'
                             % data['latitude'])

    if 'longitude' in data and data['longitude'] is not None:
        try:
            data['longitude'] = float(data['longitude'])
            if data['longitude'] < -180 or data['longitude'] > 180:
                raise ValueError
        except ValueError:
            # Unable to convert to float or out-of-range
            raise ValueError(
                'Invalid longitude "%s", must be -180 <= lat <= 180' %
                (data['longitude']))

    if 'orientation' in data and data['orientation'] is not None:
        try:
            data['orientation'] = Orientation.lookup(data['orientation'])
        except KeyError:
            raise ValueError('Unknown orientation "%s"; known orientations %r'
                             % (data['orientation'], Orientation.names()))

    if 'shape' in data and data['shape'] is not None:
        try:
            data['shape'] = Shape.lookup(data['shape'])
        except KeyError:
            raise ValueError('Unknown shape "%s"; known shapes %r' %
                             (data['shape'], Shape.names()))

    if 'background_color' in data and data['background_color'] is not None:
        try:
            data['background_color'] = Color.lookup(data['background_color'])
        except KeyError:
            raise ValueError('Unknown color "%s"; known colors %r' %
                             (data['background_color'], Color.names()))

    if 'alphanumeric_color' in data and data['alphanumeric_color'] is not None:
        try:
            data['alphanumeric_color'] = \
                Color.lookup(data['alphanumeric_color'])
        except KeyError:
            raise ValueError('Unknown color "%s"; known colors %r' %
                             (data['alphanumeric_color'], Color.names()))

    return data


class Targets(View):
    """POST new target."""

    @method_decorator(require_login)
    def dispatch(self, *args, **kwargs):
        return super(Targets, self).dispatch(*args, **kwargs)

    def post(self, request):
        data = json.loads(request.body)

        # Target type is required.
        if 'type' not in data:
            return HttpResponseBadRequest('Target type required.')

        latitude = data.get('latitude')
        longitude = data.get('longitude')

        # Require zero or both of latitude and longitude.
        if (latitude is not None and longitude is None) or \
            (latitude is None and longitude is not None):
            return HttpResponseBadRequest(
                'Either none or both of latitude and longitude required.')

        try:
            data = normalize_data(data)
        except ValueError as e:
            return HttpResponseBadRequest(str(e))

        l = None
        if latitude is not None and longitude is not None:
            l = GpsPosition(latitude=data['latitude'],
                            longitude=data['longitude'])
            l.save()

        # Use the dictionary get() method to default non-existent values to None.
        t = Target(user=request.user,
                   target_type=data['type'],
                   location=l,
                   orientation=data.get('orientation'),
                   shape=data.get('shape'),
                   background_color=data.get('background_color'),
                   alphanumeric=data.get('alphanumeric', ''),
                   alphanumeric_color=data.get('alphanumeric_color'),
                   description=data.get('description', ''))
        t.save()

        return JsonResponse(t.json(), status=201)


class TargetsId(View):
    """Get or update a specific target."""

    @method_decorator(require_login)
    def dispatch(self, *args, **kwargs):
        return super(TargetsId, self).dispatch(*args, **kwargs)

    def find_target(self, request, pk):
        """Lookup requested Target model.

        Only the request's user's targets will be returned.

        Args:
            request: Request object
            pk: Target primary key

        Raises:
            Target.DoesNotExist: pk not found
            ValueError: Target not owned by this user.
        """
        target = Target.objects.get(pk=pk)

        # We only let users get their own targets
        if target.user != request.user:
            raise ValueError("Accessing target %d not allowed" % pk)

        return target

    def get(self, request, pk):
        try:
            target = self.find_target(request, int(pk))
        except Target.DoesNotExist:
            return HttpResponseNotFound('Target %s not found' % pk)
        except ValueError as e:
            return HttpResponseForbidden(str(e))

        return JsonResponse(target.json())

    def put(self, request, pk):
        try:
            target = self.find_target(request, int(pk))
        except Target.DoesNotExist:
            return HttpResponseNotFound('Target %s not found' % pk)
        except ValueError as e:
            return HttpResponseForbidden(str(e))

        data = json.loads(request.body)

        try:
            data = normalize_data(data)
        except ValueError as e:
            return HttpResponseBadRequest(str(e))

        # We update any of the included values, except id and user
        if 'type' in data:
            target.target_type = data['type']
        if 'orientation' in data:
            target.orientation = data['orientation']
        if 'shape' in data:
            target.shape = data['shape']
        if 'background_color' in data:
            target.background_color = data['background_color']
        if 'alphanumeric' in data:
            target.alphanumeric = data['alphanumeric']
        if 'alphanumeric_color' in data:
            target.alphanumeric_color = data['alphanumeric_color']
        if 'description' in data:
            target.description = data['description']

        # Location is special because it is in a GpsPosition model

        # If lat/lon exist and are None, the user wants to clear them.
        # If they exist and are not None, the user wants to update/add them.
        # If they don't exist, the user wants to leave them alone.
        clear_lat = False
        clear_lon = False
        update_lat = False
        update_lon = False

        if 'latitude' in data:
            if data['latitude'] is None:
                clear_lat = True
            else:
                update_lat = True

        if 'longitude' in data:
            if data['longitude'] is None:
                clear_lon = True
            else:
                update_lon = True

        if (clear_lat and not clear_lon) or (not clear_lat and clear_lon):
            # Location must be cleared entirely, we can't clear just lat or
            # just lon.
            return HttpResponseBadRequest(
                'Only none or both of latitude and longitude can be cleared.')

        if clear_lat and clear_lon:
            target.location = None
        elif update_lat or update_lon:
            if target.location is not None:
                # We can directly update individual components
                if update_lat:
                    target.location.latitude = data['latitude']
                if update_lon:
                    target.location.longitude = data['longitude']
                target.location.save()
            else:
                # We need a new GpsPosition, this requires both lat and lon
                if not update_lat or not update_lon:
                    return HttpResponseBadRequest(
                        'Either none or both of latitude and longitude required.')

                l = GpsPosition(latitude=data['latitude'],
                                longitude=data['longitude'])
                l.save()
                target.location = l

        target.save()

        return JsonResponse(target.json())
