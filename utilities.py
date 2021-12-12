import mapadroid.utils.pluginBase
from flask import render_template, Blueprint, request, jsonify
from mapadroid.madmin.functions import auth_required
from mapadroid.madmin.functions import generate_coords_from_geofence, get_geofences
import os, time, ast
from datetime import datetime, timedelta


class MadUtilitiesPlugin(mapadroid.utils.pluginBase.Plugin):
    """This plugin is just the identity function: it returns the argument
    """
    # =============================================================================================
    def __init__(self, mad):
    # =============================================================================================
        super().__init__(mad)

        self._rootdir = os.path.dirname(os.path.abspath(__file__))

        self._mad = mad

        self._pluginconfig.read(self._rootdir + "/plugin.ini")
        self._versionconfig.read(self._rootdir + "/version.mpl")
        self.author = self._versionconfig.get("plugin", "author", fallback="unknown")
        self.url = self._versionconfig.get("plugin", "url", fallback="https://www.maddev.eu")
        self.description = self._versionconfig.get("plugin", "description", fallback="unknown")
        self.version = self._versionconfig.get("plugin", "version", fallback="unknown")
        self.pluginname = self._versionconfig.get("plugin", "pluginname", fallback="https://www.maddev.eu")
        self.staticpath = self._rootdir + "/static/"
        self.templatepath = self._rootdir + "/template/"

        self._routes = [
             ("/utilities_quests", self.util_quests),
             ("/utilities_util_q", self.util_q),
             ("/utilities_stops", self.util_stops),
             ("/utilities_sstats", self.util_sstats),
             ("/utilities_del_oldpoi", self.del_oldpoi),
             ("/utilities_gyms", self.util_gyms),
             ("/utilities_pokemon", self.util_pokemon),
        ]

        self._hotlink = [
            ("Quest Utilities",    "utilities_quests",  "Count, or delete, today's quests from before time X"),
            ("Pokestop Utilities", "utilities_stops",   "Utilities for pokestops"),
            ("Gym Utilities",      "utilities_gyms",    "Utilities for gyms"),
            ("Pokemon Utilities",  "utilities_pokemon", "Utilities for pokemon"),
        ]

        if self._pluginconfig.getboolean("plugin", "active", fallback=False):
            self._plugin = Blueprint(str(self.pluginname), __name__, static_folder=self.staticpath,
                                     template_folder=self.templatepath)

            for route, view_func in self._routes:
                self._plugin.add_url_rule(route, route.replace("/", ""), view_func=view_func)

            for name, link, description in self._hotlink:
                self._mad['madmin'].add_plugin_hotlink(name, self._plugin.name+"."+link.replace("/", ""),
                                                       self.pluginname, self.description, self.author, self.url,
                                                       description, self.version)


    # =============================================================================================
    def perform_operation(self):
    # =============================================================================================
        """The actual implementation of the identity plugin is to just return the
        argument
        """

        # do not change this part ▽▽▽▽▽▽▽▽▽▽▽▽▽▽▽
        if not self._pluginconfig.getboolean("plugin", "active", fallback=False):
            return False
        self._mad['madmin'].register_plugin(self._plugin)
        # do not change this part △△△△△△△△△△△△△△△

        # load your stuff now

        return True


    # =============================================================================================
    def delete_quests_before_time(self, before_timestamp=None, from_fence=None, delete_quests=False):
    # =============================================================================================
        """
        Delete all quests before the given timestamp (UTC) from the given fenced in area.
        Return number of matching (delete_quests=False) or deleted (delete_quests=True) quests.
         - before_timestamp is a UTC timestamp: 1587414020 (or similar), None means delete all quests from today
         - from_fence is a string in format: "lat1 lon1, lat2 lon2, lat3 lon3, lat1 lon1", None means delete from all areas
           note: no comma between lat lon, and first point equals last point
        """

        quest_info = self._mad['db_wrapper'].quests_from_db(fence=from_fence)

        try:
            if before_timestamp != None:
                int(before_timestamp)
        except: # if before_timestamp is not a valid integer, set it to 0 so we don't affect any quests
            self._mad['logger'].info("dbWrapper::delete_quests_before_time - invalid value for beforetime ({}), setting to 0".format(before_timestamp))
            before_timestamp = 0

        quest_ids = []
        for q in quest_info:
            if before_timestamp != None:
                if int(quest_info[q]['quest_timestamp']) < int(before_timestamp):
                    quest_ids.append( '"' + quest_info[q]['pokestop_id'] + '"')
            else:
                quest_ids.append( '"' + quest_info[q]['pokestop_id'] + '"')

        self._mad['logger'].info("dbWrapper::delete_quests_before_time - found {} quest(s)".format(len(quest_ids)))

        if delete_quests and len(quest_ids) > 0:
            query = (
                "DELETE "
                "FROM trs_quest "
                "WHERE GUID in ({})".format(str(','.join(quest_ids)))
            )
            self._mad['db_wrapper'].execute(query, commit=True)
            self._mad['logger'].info("dbWrapper::delete_quests_before_time - **DELETED** {} quest(s)".format(len(quest_ids)))

        # return number of quests matching criteria
        return len(quest_ids)


    # =============================================================================================
    def point_in_poly(self, x, y, poly):
    # =============================================================================================
      # Improved point in polygon test which includes edge
      # and vertex points
      inside = True
      # check if point is a vertex
      if (x,y) in poly: return inside

      # check if point is on a boundary
      for i in range(len(poly)):
         p1 = None
         p2 = None
         if i==0:
            p1 = poly[0]
            p2 = poly[1]
         else:
            p1 = poly[i-1]
            p2 = poly[i]
         if p1[1] == p2[1] and p1[1] == y and x > min(p1[0], p2[0]) and x < max(p1[0], p2[0]):
            return inside

      n = len(poly)
      inside = False

      p1x,p1y = poly[0]
      for i in range(n+1):
         p2x,p2y = poly[i % n]
         if y > min(p1y,p2y):
            if y <= max(p1y,p2y):
               if x <= max(p1x,p2x):
                  if p1y != p2y:
                     xints = (y-p1y)*(p2x-p1x)/(p2y-p1y)+p1x
                  if p1x == p2x or x <= xints:
                     inside = not inside
         p1x,p1y = p2x,p2y

      return inside


    # =============================================================================================
    def point_in_area(self, lat, lon, gf_inc, gf_exc):
    # =============================================================================================
      # geofence = [instance, name, polys-dictionary], {name1: poly1, name2: poly2, ... }
      in_inc = 0
      in_exc = 0
      if self.point_in_poly(lat, lon, gf_inc):
        in_inc = 1
      if gf_exc:
        for key in gf_exc[2]:
          if self.point_in_poly(lat, lon, gf_exc[2][key]):
            in_exc = 1
            break
      if in_inc == 1 and in_exc == 0:
        return True
      return False


    # =============================================================================================
    def parse_geofences_file(self, geofence_file):
    # =============================================================================================
        # res_gf = [ (int, int, str, str: '["[name1]", "float,float", etc, "[name2]", "float,float", etc ]' ), etc ]
        geofences = []
        # Read coordinates of areas from file.
        if geofence_file:
            with open(geofence_file) as f:
                for line in f:
                    line = line.strip()
                    if len(line) == 0:  # Empty line.
                        continue
                    elif line.startswith("["):  # Name line.
                        name = line.replace("[", "").replace("]", "")
                        geofences.append({
                            'name': name,
                            'polygon': []
                        })
                    else:  # Coordinate line.
                        lat, lon = line.split(",")
                        LatLon = {'lat': float(lat), 'lon': float(lon)}
                        geofences[-1]['polygon'].append(LatLon)
        return geofences


    # =============================================================================================
    def convert_path_list(self, path):
    # =============================================================================================
      # return list of [lat,lon,count] lists
      res = []
      for wp in path:
        wp = wp.strip()
        if len(wp) == 0 or "," not in wp: continue
        lat,lon = wp.split(",")
        lat = float(lat.strip())
        lon = float(lon.strip())
        if lat < -90 or lat > 90: continue
        if lon < -180 or lon > 180: continue
        res.append( [lat,lon,0] )
      return res


    # =============================================================================================
    def get_poly_dict(self, gf_str, gf_name):
    # =============================================================================================
      # return dict: {name : list of (lat,lon) tuples}
      res = {}
      cur_name = ''
      for e in gf_str:
        if e.startswith('['):
          e = e.replace("[", "").replace("]", "")
          cur_name = e
          res[cur_name] = []
          continue
        e = e.strip()
        if len(e) == 0 or "," not in e: continue
        lat,lon = e.split(",")
        lat = float(lat.strip())
        lon = float(lon.strip())
        if lat < -90 or lat > 90: continue
        if lon < -180 or lon > 180: continue
        if cur_name == '':
          cur_name = str(gf_name)
          res[cur_name] = []
        res[cur_name].append( (lat,lon) )
      return res


    # =============================================================================================
    def latlon_close(self, lat_wp, lon_wp, lat_ps, lon_ps, offset):
    # =============================================================================================
      lat_diff = abs( lat_wp - lat_ps )
      lon_diff = abs( lon_wp - lon_ps )
      lon_diff_360 = 360.0 - lon_diff # to try to account for lon's close to +/-180
      if lat_diff <= offset and (lon_diff <= offset or lon_diff_360 <= offset):
        return True
      return False


    # =============================================================================================
    def happened_today(self, time_str, tz_offset):
    # =============================================================================================
      # time_str = "2020-08-21 02:38:44"
      # time_str = "2020-07-13 16:42:07"
      #print('time_str = ' + str(time_str))
      #print('tz_offst = ' + str(tz_offset))
      # dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S') # date of time_str, assumed to be utc
      if isinstance(time_str, int):
        dt = datetime.utcfromtimestamp(time_str)
      else:
        dt = time_str
      td = datetime.utcnow() # today's date/time in utc time
      dt_tz = dt + timedelta(hours=tz_offset)
      td_tz = td + timedelta(hours=tz_offset)
      if dt_tz.date() == td_tz.date():
        return True
      return False


    # =============================================================================================
    def days_diff(self, time_str, tz_offset):
    # =============================================================================================
      # dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S') # date of time_str, assumed to be utc
      if isinstance(time_str, int):
        dt = datetime.utcfromtimestamp(time_str)
      else:
        dt = time_str
      td = datetime.utcnow() # today's date/time in utc time
      dt_tz = dt + timedelta(hours=tz_offset)
      td_tz = td + timedelta(hours=tz_offset)
      return (td_tz.date() - dt_tz.date()).days


    # =============================================================================================
    def gather_stop_stats(self):
    # =============================================================================================
        query1 = ("SELECT area_id, geofence_included, geofence_excluded, routecalc FROM settings_area_pokestops")
        query2 = ("SELECT pokestop_id, latitude, longitude, last_updated, name FROM pokestop")
        query3 = ("SELECT geofence_id, instance_id, name, fence_data FROM settings_geofence") # there can be multiple [named] areas in fence_data
        query4 = ("SELECT routecalc_id, instance_id, routefile FROM settings_routecalc")
        query5 = ("SELECT GUID, quest_timestamp FROM trs_quest")
        query6 = ("SELECT area_id, instance_id, name, mode FROM settings_area")

        # geo_f = { gfid : str(geofence_id), inid : str(instance_id),
        #           gfname : name, gfpoly : {name1 : [(x1,y1), (x2,y2), etc], name2 : [poly], etc} }

        # print('Gathering data...')
        self._mad['logger'].info(" *** utilities plugin: gather_stop_stats: executing queries")

        res_ar = self._mad['db_wrapper'].execute(query1) # 7 areas (small)
        res_ps = self._mad['db_wrapper'].execute(query2) # ~14000 results
        res_gf = self._mad['db_wrapper'].execute(query3) # 7 geofences (medium)
        res_rc = self._mad['db_wrapper'].execute(query4) # 110 long strings
        res_qs = self._mad['db_wrapper'].execute(query5) # ~2000 results
        res_ad = self._mad['db_wrapper'].execute(query6) # 14 results (small)

        # calculate timezone offset, in hours, based on local system time
        lt = time.localtime()
        tz_offset = lt.tm_gmtoff / 3600.0

        # print('Processing data...')
        self._mad['logger'].info(" *** utilities plugin: gather_stop_stats: processing data")

        # res_ar = [ (int, int, none or int, int), etc ]
        # res_ps = [ (str, float, float, datetime.datetime(y,m,d,h,m,s), str ), etc ]
        # res_gf = [ (int, int, str, str: '["[name1]", "float,float", etc, "[name2]", "float,float", etc ]' ), etc ]
        # res_rc = [ (int, int, str: '["float,float", etc ]' ), etc ]
        # res_qs = [ (str, int), etc ]
        # res_ad = [ (int, int, str, str), etc ]

        # geo_f = { gfid : geofence_id, inid : instance_id, gfname : name, gfpoly : {name1 : [(x1,y1), (x2,y2), etc], name2 : [poly], etc} }
        all_gf = {}
        for gf in res_gf:
          dict = self.get_poly_dict(ast.literal_eval(gf[3]), gf[2])
          all_gf[ gf[0] ] = [gf[1], gf[2], dict] # [instance, name, polys-dict], dict because there can be more than one [named] area per geofence

        all_rc = []
        for rc in res_rc:
          path_list = ast.literal_eval(rc[2]) # list of 'lat, lon' strings
          new_path_list = self.convert_path_list(path_list) # create list of (lat, lon) tuples (containing floats)
          all_rc.append( [rc[0], rc[1], new_path_list] ) # routecalc_id, instance_id, new_path_list = [ [lat1,lon1,count1], ... ]
        # new_path_list = [ [lat,lon,count1], ... ] where count is filled in later by how many pokestops are "close" to this way-point
        # need to test how close is close, but will try within +/- 0.0001 of lat/lon to count as wp covering the stop

        # quest/stop data:
        qs_data = {}
        ts = 0 # total stops
        st = 1 # stops scanned today (last_updated today)
        rl = 2 # quest route length
        qt = 3 # quests scanned today
        nw = 4 # stops not covered by a way-point in a quest route
        ww = 5 # way-point in a quest route that does not have a stop beneath it
        nn = 6 # number of stops with no name (probably new)
        ns = 7 # stops not scanned today
        n7 = 8 # stops not scanned in the last 7 days
        n8 = 9 # stops not scanned for 8 or more days


        for ps in res_ps: # (pokestop_id, latitude, longitude, last_updated, name)
          for area in res_ar: # (area_id, geofence_included, geofence_excluded, routecalc)
            name = ''
            for ad in res_ad: # (area_id, instance_id, name, mode)
              if ad[0] == area[0]:
                name = ad[2]
                break
            gf_inc = all_gf[area[1]] # [instance, name, polys-dict]
            if area[2] == None:
              gf_exc = None
            else:
              gf_exc = all_gf[area[2]] # [instance, name, polys-dict]
            for key in gf_inc[2]:
              if (name, key) not in qs_data:
                qs_data[ (name, key) ] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
              qs_info = qs_data[ (name, key) ]
              if self.point_in_area(ps[1], ps[2], gf_inc[2][key], gf_exc):
                qs_info[ts] += 1
              else:
                continue
              if self.happened_today(ps[3], tz_offset):
                qs_info[st] += 1
              else:
                qs_info[ns] += 1
                if self.days_diff(ps[3], tz_offset) <= 7:
                  qs_info[n7] += 1
                else:
                  qs_info[n8] += 1
              if ps[4] in [None, '']:
                qs_info[nn] += 1
              for rc_entry in all_rc:
                if rc_entry[0] == area[3]:
                  qs_info[rl] = len(rc_entry[2])
                  stop_found = 0
                  for wp in rc_entry[2]:
                    if self.latlon_close(wp[0], wp[1], ps[1], ps[2], 0.00003):
                      wp[2] += 1
                      stop_found = 1
                    else:
                      qs_info[ww] += 1
                  if stop_found == 0:
                    qs_info[nw] += 1
                  break
              for q_entry in res_qs:
                if q_entry[0] == ps[0]:
                  if self.happened_today(q_entry[1], tz_offset):
                    qs_info[qt] += 1
                    break

        self._mad['logger'].info(" *** utilities plugin: gather_stop_stats: packing data")

        # Count how many way-points didn't have a stop beneath them...
        # And, print out the info...
        #
        # print('area_name, poly_name, total_stops, scanned_today, q_route_len,
        #          q_today, non-wp-stops, wp-wo-stops, no-name-stops, ns_today, ns17d, ns8p')
        #
        # put data into list and return it
        stats = []
        for area in res_ar: # (area_id, geofence_included, geofence_excluded, routecalc)
          area_id = 0
          name = ''
          for ad in res_ad: # (area_id, instance_id, name, mode)
            if ad[0] == area[0]:
              area_id = area[1] # return the geofence_id
              name = ad[2]
              break
          gf_inc = all_gf[area[1]] # [instance, name, polys-dict]
          for key in gf_inc[2]:
            if (name, key) not in qs_data:
              continue
            qs_info = qs_data[ (name, key) ]
            for rc_entry in all_rc:
              if rc_entry[0] == area[3]:
                wp_missing = 0
                for wp in rc_entry[2]:
                  if wp[2] == 0:
                    wp_missing += 1
                qs_info[ww] = wp_missing
            bt = ('<button type="button" data-toggle="tooltip" title="Delete old pokestops" ' +
                  'class="delete btn btn-danger btn-sm confirm" data-areaid="' + str(name) +
                  '" data-name="' + str(key) + '"><div class="delete_div" ' +
                  'style="display:inline;"><i class="fa fa-trash"></i></div></button>')
            # old code to try to include a 'recalc-route-button'
            #bt = ('<button type="button" data-toggle="tooltip" title="Delete old pokestops" ' +
            #      'class="delete btn btn-danger btn-sm confirm" data-areaid="' + str(name) +
            #      '" data-name="' + str(key) + '"><div class="delete_div" ' +
            #      'style="display:inline;"><i class="fa fa-trash"></i></div></button> ' +
            #      '<button type="button" data-toggle="tooltip" title="Recalc quest route" ' +
            #      'class="recalc btn btn-info btn-sm confirm" data-areaid="' + str(name) + '">' +
            #      '<div class="recalc_div" style="display:inline;"><i class="fas fa-undo"></i></div></button>')
            # {data: 'areaName', title: 'Area Name'},
            # {data: 'polyName', title: 'Poly Name'},
            # {data: 'totalStops', title: 'Total Stops'},
            # {data: 'scannedToday', title: 'Scanned Today'},
            # {data: 'routeLength', title: 'Route Length'},
            # {data: 'questsToday', title: 'Quests Today'},
            # {data: 'nonWayPointStops', title: 'Non-WP Stops'},
            # {data: 'nonStopWayPoints', title: 'Non-Stop WPs'},
            # {data: 'noNameStops', title: 'Nameless Stops'},
            # {data: 'notScannedToday', title: 'Not Scanned Today'},
            # {data: 'notScanned17', title: 'Not Scanned 1-7 days'},
            # {data: 'notScanned8p', title: 'Not Scanned 8+ days'},
            # stats[str(name) + '_' + str(key)] = ','.join(str(x) for x in [str(name), str(key)] + qs_info)
            stats.append({
              'areaName'        : str(name),
              'polyName'        : str(key),
              'totalStops'      : str(qs_info[0]),
              'scannedToday'    : str(qs_info[1]),
              'routeLength'     : str(qs_info[2]),
              'questsToday'     : str(qs_info[3]),
              'nonWayPointStops': str(qs_info[4]),
              'nonStopWayPoints': str(qs_info[5]),
              'noNameStops'     : str(qs_info[6]),
              'notScannedToday' : str(qs_info[7]),
              'notScanned17'    : str(qs_info[8]),
              'notScanned8p'    : str(qs_info[9]),
              'buttons'         : str(bt)
            })
        self._mad['logger'].info(" *** utilities plugin: gather_stop_stats: sending data")
        return jsonify(stats)


    # =============================================================================================
    def gen_coords_from_geofence(self, mapping_manager, data_manager, fence):
    # =============================================================================================
        fence_string = []
        geofences = get_geofences(mapping_manager, data_manager)
        coordinates = []
        for name, fences in geofences.items():
            for fname, coords in fences.get('include').items():
                if fname != fence:
                    continue
                coordinates.append(coords)

        for coord in coordinates[0]:
            fence_string.append(str(coord[0]) + " " + str(coord[1]))

        fence_string.append(fence_string[0])
        return ",".join(fence_string)


    # =============================================================================================
    def get_areas(self, mapping_manager, data_manager, area_type=None):
    # =============================================================================================
        fence_list = []
        fence_list.append('All')
        if area_type not in ['pokestops', 'raids_mitm', 'mon_mitm', 'iv_mitm']:
            return fence_list

        possible_fences = get_geofences(mapping_manager, data_manager, area_type)
        for possible_fence in get_geofences(mapping_manager, data_manager, area_type):
            for subfence in possible_fences[possible_fence]['include']:
                if subfence in fence_list:
                    continue
                fence_list.append(subfence)

        return fence_list


    @auth_required
    # =============================================================================================
    def util_quests(self):
    # =============================================================================================
        # fence = request.args.get("fence", None)
        # stop_fences = get_quest_areas(self._mapping_manager, self._data_manager)
        fence = request.args.get("fence", None)
        fence_list = self.get_areas(self._mad['mapping_manager'], self._mad['data_manager'], area_type='pokestops')
        return render_template('utilities_quests.html', pub=False,
                               header="Quest Maintenance", title="Quest Maintenance",
                               subtab='quests', fence=fence, fence_list=fence_list)


    @auth_required
    # =============================================================================================
    def util_q(self):
    # =============================================================================================
        user_fence  = request.args.get("fence", "all")
        timestamp   = request.args.get("beforetime", "none")
        user_action = request.args.get("action", "count") # default to the counting option
        bt = None if timestamp == "none" else timestamp
        dq = True if user_action == "delete" else False
        if user_fence.lower() == "all":
            ff = None
        else:
            ff = generate_coords_from_geofence(self._mad['mapping_manager'], self._mad['data_manager'], user_fence)

        res = self.delete_quests_before_time(before_timestamp=bt, from_fence=ff, delete_quests=dq)

        return ("Deleted " if dq else "Found ") + str(res) + (" quest" + "s" if res != 1 else "")


    @auth_required
    # =============================================================================================
    def util_stops(self):
    # =============================================================================================
        fence = request.args.get("fence", None)
        fence_list = self.get_areas(self._mad['mapping_manager'], self._mad['data_manager'], area_type='pokestops')
        return render_template('utilities_stops.html', pub=False,
                               header="Pokestop Maintenance", title="Pokestop Maintenance",
                               subtab='stops', fence=fence, fence_list=fence_list)


    @auth_required
    # =============================================================================================
    def util_sstats(self):
    # =============================================================================================
        self._mad['logger'].info(" *** utilities plugin: util_sstats: gathering statistics on pokestops")
        return self.gather_stop_stats()


    @auth_required
    # =============================================================================================
    def del_oldpoi(self):
    # =============================================================================================
        areaname = request.args.get("areaid", None)
        poitype = request.args.get("poi", None)
        area_poly = '';
        if poitype == None:
          self._mad['logger'].info(" *** utilities plugin: del_oldpoi: poi=None, nothing to do")
          return 'no poitype specified'
        elif poitype == 'pokestops':
          self._mad['logger'].info(" *** utilities plugin: del_oldpoi: poi=pokestops")
          fence_list = self.get_areas(self._mad['mapping_manager'], self._mad['data_manager'], area_type='pokestops')
          if areaname in fence_list:
            area_poly = self.gen_coords_from_geofence(self._mad['mapping_manager'], self._mad['data_manager'], areaname)
            # delete old pokestops from poly
            query_where = "DELETE FROM pokestop WHERE last_updated < date_sub(UTC_TIMESTAMP, INTERVAL 8 DAY) "
            query_where = query_where + " and ST_CONTAINS(ST_GEOMFROMTEXT( 'POLYGON(( {} ))'), " \
                                        "POINT(pokestop.latitude, pokestop.longitude))".format(str(area_poly))
            self._mad['logger'].info(" *** utilities plugin: del_oldpoi: deleting old pokestops, " + str(areaname))
            self._mad['db_wrapper'].execute(query_where, commit=True)
            return 'success'
          else:
            return 'area not found'
        elif poitype == 'gyms':
          self._mad['logger'].info(" *** utilities plugin: del_oldpoi: poi=gyms")
          fence_list = self.get_areas(self._mad['mapping_manager'], self._mad['data_manager'], area_type='raids_mitm')
          if areaname in fence_list:
            area_poly = self.gen_coords_from_geofence(self._mad['mapping_manager'], self._mad['data_manager'], areaname)
            # delete old gyms from poly
            query_where = "DELETE FROM gym WHERE last_scanned < date_sub(UTC_TIMESTAMP, INTERVAL 8 DAY) "
            query_where = query_where + " and ST_CONTAINS(ST_GEOMFROMTEXT( 'POLYGON(( {} ))'), " \
                                        "POINT(gym.latitude, gym.longitude))".format(str(area_poly))
            self._mad['logger'].info(" *** utilities plugin: del_oldpoi: deleting old gyms, " + str(areaname))
            self._mad['db_wrapper'].execute(query_where, commit=True)
            return 'success'
          else:
            return 'area not found'
        else: # unexpected data, do nothing...
          self._mad['logger'].info(" *** utilities plugin: del_oldpoi: poi=" + str(poitype)[:20] + ", unknown, skipping")
          return 'unknown poitype'



    @auth_required
    # =============================================================================================
    def util_gyms(self):
    # =============================================================================================
        fence = request.args.get("fence", None)
        fence_list = self.get_areas(self._mad['mapping_manager'], self._mad['data_manager'], area_type='raids_mitm')
        return render_template('utilities_gyms.html', pub=False,
                               header="Gym Maintenance", title="Gym Maintenance",
                               subtab='gyms', fence=fence, fence_list=fence_list)


    @auth_required
    # =============================================================================================
    def util_pokemon(self):
    # =============================================================================================
        fence = request.args.get("fence", None)
        fence_list = self.get_areas(self._mad['mapping_manager'], self._mad['data_manager'], area_type='mon_mitm')
        return render_template('utilities_pokemon.html', pub=False,
                               header="Pokemon Maintenance", title="Pokemon Maintenance",
                               subtab='pokemon', fence=fence, fence_list=fence_list)


