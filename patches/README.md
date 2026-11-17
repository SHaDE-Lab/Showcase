# Patches for the lab's own repositories

These are proposals. Nothing here has been applied to or pushed to any SHaDE Lab repository.

## cool-routes-frontend-url-params.patch

Lets the Cool Routes web app start with a start building and a destination already chosen, from the URL:

    https://coolroutes.sensableheatscapes.com/?start=COOR&end=CRTVC

The values are searched with the app's own building search (building code or name), so `?start=COOR&end=Creativity%20Commons` works too. The route draws automatically once both are set. Without the parameters the app behaves exactly as before.

Apply to `SHaDE-Lab/Cool-Routes-Frontend` (checked against the current `main` file):

    git apply patches/cool-routes-frontend-url-params.patch

After it is deployed, this portal's embedded Cool Routes already requests `?start=COOR&end=CRTVC` (`embedQuery` in `assets/site.js`).

Please verify that `CRTVC` finds Creativity Commons in the app's building layer; if not, change `embedQuery`.

## cool-routes-frontend-postmessage.patch

Makes the Cool Routes app tell the page that embeds it two things: a building was chosen in one of the two search boxes (with Enter or from the
list), and the map was dragged. The showcase's guided tour listens for these and moves on by itself; without the patch the tour still works, but
its first two steps wait for the visitor to press **Next**. Nothing is sent when the app is opened on its own (not inside a frame).

    { source: 'cool-routes', event: 'building-selected', which: 'start' | 'end' }
    { source: 'cool-routes', event: 'map-dragged' }

Apply after the URL-parameter patch (it was made against the file with that patch applied):

    git apply patches/cool-routes-frontend-postmessage.patch

The message carries no personal data and is only posted to the embedding page; the portal accepts it only from `https://coolroutes.sensableheatscapes.com`.
