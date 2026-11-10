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
