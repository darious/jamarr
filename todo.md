# ToDo List

## Scanner
* ~~Add a sparse refresh mode that only looks for new stuff and doesn't delete old stuff~~
* ~~make the scanner notice changed files and update them and remove files that are missing from the file system~~
* make the file location relative to the config  music root varibale, so we can clone the database

## Search
* ~~Add search box to the top of the page~~
* ~~it should search in artist, album, and track title~~
* ~~it should return results live as i type~~
* ~~it should group the results into artists, albums, and tracks~~
* ~~and should jump to the relevant artist or album page, when they are selected and have play and queue icons for each~~
* make serach work at any part of the search term, right now "Ed Shee" works but "Sheeran" does not


## multi user
* ~~allow some sort of fingerprinting so that client and server can serve multiple users~~
* ~~if a 2nd user picks the same renderer and the 1st, then it should pick up the queue and playback position and allow both to control the same renderer~~


## Artist page
* pull all the albums for the artist and add a missing album section to the bottom of the page, ideally with a button to grab the qobuz id for the album on to the clipboard.


## Album page
* ~~split multi disc albums so we can see each disc~~
* ~~make it feel more like the artist page, add links to the album in musicbrainz, make sue the album art is the same size and locatgion as the artist artwork on the artist page~~


## playback
* ~~play pause button not working for upnp post a page reload~~
* ~~fix playback pausing when browser tab does not have the focus~~
* ~~Fix where the whole album is added to the queue when i click play on a single album track~~
* fix where we're adding tracks to the history twice (front and backend I think)

