## Version 0.4
* Quest Utils available:
  * Count/delete today's quests from before time X for one or all areas
* Pokestop Utils available:
  * Gather stats on quest routes
    * Route length
    * Number of quests scanned today
    * Stops seen today
    * Stops not seen for 1-7 days
    * Stops not seen for 8+ days
    * Whether each waypoint in the route has a stop beneath it
    * Whether each stop has a route waypoint covering it.
    * A trash can icon to delete pokestops from your database that are 8+ days old
* Gym Utils planned for a future update

## Installation Notes
* Download utilities plugin mp file
* Navigate to `madmin -> System -> MAD Plugins`
* Click "Choose File" and select the downloaded mp file
* Click the "Upload" button
* Log in to your MAD server and edit the `<mad>/plugins/utilities/plugin.ini` so that it looks like:
```
[plugin]
active = true
```
* Restart MAD and you can then access these utilities at `madmin -> System -> MAD Plugins`
