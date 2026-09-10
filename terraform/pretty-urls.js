/*
 * Viewer-request function: /tracks -> /tracks.html
 *
 * Only extension-less paths are rewritten. That is the whole trick, and it is
 * what keeps three things working at once:
 *
 *   /tracks.html            untouched — the blog embeds this exact URL in an
 *                           iframe, and a redirect would be one more hop for
 *                           every reader of that post
 *   /data/latest.json       untouched — the aggregation job's own paths
 *   /tracks/geometry.json   untouched — a real directory that happens to share
 *                           a name with a page
 *
 * So both spellings resolve to the same object and neither is a redirect. The
 * pages name the pretty one in a <link rel="canonical"> so search engines pick
 * a side.
 *
 * ES5 only: CloudFront Functions are not a browser and not Node.
 */
function handler(event) {
    var request = event.request;
    var uri = request.uri;

    // The dashboard is the front door, as it was before the landing page moved
    // to robbiea.co.uk. Anyone who bookmarked the bare host keeps what they had.
    if (uri === '/') {
        request.uri = '/passenger-hours.html';
        return request;
    }

    // /tracks/ and /tracks are the same page.
    if (uri.length > 1 && uri.charAt(uri.length - 1) === '/') {
        uri = uri.substring(0, uri.length - 1);
    }

    // A dot anywhere in the last segment means the client asked for a file.
    var lastSlash = uri.lastIndexOf('/');
    if (uri.indexOf('.', lastSlash) === -1) {
        request.uri = uri + '.html';
    }

    return request;
}
