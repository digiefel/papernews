# Technical outline

Purpose: a simple HN-like website for research discussion. Users post and discuss research-relevant links or text: papers, manuals, code, datasets, talks, websites, questions, notes, short explanations of their own work, and anything else useful to a research community.

It is not a paper database, citation manager, academic LinkedIn, protocol project, federation project, reputation game, or subreddit clone.

The core product is a fast, server-rendered website with global public discussion, scoped community views, pseudonymous accounts, lightweight moderation, and old-school personal pages.

# Product constraints

The site should feel lightweight and effortless like HN.

Core actions must work without JavaScript.

No frontend framework.

Modular, simple architecture.

No rich editor.

No live preview.

No image uploads or embeds in v1.

No user karma, badges, follower counts, leaderboards, or public status metrics.

No required arXiv/DOI/paper-specific workflow.

Simple, fast, effortless dev workflow and deployment.

# Stack

Use Django + SQLite + server-rendered HTML + very small CSS.

Django handles routing, templates, forms, auth, sessions, CSRF protection, admin views, validation, and migrations.

SQLite stores persistent state.

The interface is normal HTML pages and forms.

Deployment can be a normal Linux service or Docker later. The application should not depend on Docker-specific assumptions.

A simple request flow is:

browser → web server/reverse proxy → Django app → SQLite database

# Core concepts

The main content object is a submission.

A submission is not necessarily a paper. It can be a link, text post, manual, dataset, repo, talk, question, note, website, or paper explanation.

A comment is discussion attached to a submission or another comment.

A community is a user-facing scoped view/feed, such as `/c/solid-state-physics`, `/c/neuroscience`, `/c/my-lab`, or `/c/some-journal`.

A scope is the internal technical layer that says where a submission appears or who can see it.

Communities are views, not hard containers. A submission can appear in multiple communities.

Public discussion is canonical. Private/community-only discussion can exist, but should be an overlay rather than the main structure.

# Submissions

A submission has:

title
optional URL
optional text
author
creation time
optional lightweight metadata
votes
comments
saves
one or more scopes/community appearances

Lightweight metadata may include:

authors
year
source/venue
DOI or URL if provided through BibTeX or identifier input

This metadata is optional.

A user can create a submission from:

a link
a text post
an identifier
pasted BibTeX

BibTeX parsing is only a convenience. It should parse a few fields if present: title, author, year, journal/booktitle, DOI, URL. It then creates a normal submission.

If pasted BibTeX lacks enough information to create a useful submission, it can fail.

# Comments

A comment has:

text
author
time
votes
parent submission
optional parent comment
visibility/scope if private or community-only

User-facing comment metadata should stay minimal: commenter, time, votes.

Comments should not have rich academic metadata.

Markup should be tiny:

plain text
links
quotes
code blocks
math with `$...$` and `$$...$$`

# Users

Users have stable pseudonymous accounts.

A user may have a verified checkmark.
The checkmark only means the account verified some academic or research affiliation. It does not reveal identity, institution, rank, or real name unless the user chooses to do so.

There is no user karma.

Votes affect ranking of submissions/comments only. They do not produce public user scores.

User pages have two parts:

default HN-like activity page showing submissions and comments
custom old-school personal HTML page

The custom page is stored as sanitized HTML in the user profile. It should allow the user to control their own personal space, probably without JavaScript.

# Communities

A community is a scoped feed/view.

Examples:

`/c/solid-state-physics`
`/c/neuroscience`
`/c/my-lab`
`/c/some-journal`

A community can be public or private.

A community has:

name
slug
public/private flag
members if private
moderators
feed of submissions
optional short description or about text

A community does not need elaborate rules in v1. At most, it can have a short description or one-line posting guidance shown on the community page.

Communities are not meant to solve academic taxonomy. Papers and research objects do not belong to fixed boundaries. Communities are just curated/moderated views.

Automated communities/feeds may have a reason to exist, but they may steer towards a social media / algorithmic feed and are therefore to treated with care and in the future.

# Scopes

Scope is the internal technical concept.

A scope says where/for whom a submission or comment is visible.

Possible scopes:

global
community
private/user

This keeps the product flexible.

A submission can be public/global.

A submission can appear in one or more communities.

A private lab/group submission can use the same submission model but have restricted visibility.

This allows the global-vs-private tension to be decided carefully later without rewriting the core data model.

# Moderation

There are two levels of moderation.

Global moderation handles site-wide problems: spam, abuse, illegal content, sockpuppets, and obvious bad behavior. Global moderation can affect the whole site.

Community moderation affects only that community’s view. Community moderators can hide a submission from their community, approve/remove members in private communities, and manage the community’s short description/about text.

Community moderators should not be able to delete global submissions, delete global comments, ban users site-wide, or change user accounts.

Moderation actions should be logged and reversible.

# Database shape

Use SQLite.

Core tables/models:

`users`
Django’s built-in user table. Stores login/account data.

`profiles`
Extra user data: user, verified flag, custom sanitized HTML page, timestamps.

`communities`
Community data: slug, name, description/about text, public/private flag, timestamps.

`community_memberships`
User/community relationship: member or moderator.

`submissions`
Top-level posts: title, URL, text, author, time, optional lightweight metadata.

`submission_scopes`
Where a submission appears: global, community, or private/user. This is the flexible layer.

`comments`
Text comments attached to a submission, optionally attached to a parent comment. Comments may be public or community/private scoped.

`submission_votes`
One user’s vote on one submission.

`comment_votes`
One user’s vote on one comment.

`saves`
Private bookmarks. A save means a user saved a submission to find later. It is not public by default and not shown on the user page unless a later feature explicitly allows that.

`moderation_actions`
Audit log: moderator, community if applicable, target, action, reason, timestamp.

# User-facing pages

Global front page: ranked public submissions.

New page: recent public submissions.

Submission page: title, link or text, lightweight metadata if present, submitter/time/community context, votes, save action, comments.

Community page: community name, optional short description, feed of submissions visible in that community.

User page: sanitized old-school HTML page controlled by the user; default to HN-like activity view.

Saved page: private list of saved submissions.

Submit page: create from link, text, identifier, or BibTeX paste.

# Usage flows
A user submits a link. They paste a URL, add or edit the title, choose where it should appear, and submit. The result is a normal submission with comments and votes.
A user submits a text post. They write a title and body, choose where it should appear, and submit. This can be a question, note, short explanation of their own paper, reading note, or discussion prompt.
A user submits BibTeX or an identifier. The app extracts only enough to prefill a normal submission: title, URL/DOI if present, authors, year, source. It still becomes a normal submission, not a citation object.
A user comments. They write plain text, optionally with links, quotes, code, or math. The comment appears in the public thread unless posted in a private/community-only context.
A user saves something. It goes into their private saved list so they can find it later.
A user visits a community. They see a scoped feed of submissions visible in that community. Public communities are field-like or topic-like; private communities are for labs, seminars, reading groups, or friends.
A lab uses a private community. Members post links/text, save useful submissions, and discuss either public submissions privately or private group-only submissions.
A moderator hides something from a community. That affects only that community view. Global moderators handle site-wide problems.
A user edits their personal page. By default it looks HN-like, but they can also maintain a custom old-school HTML page under their username.
Zero-user value
With no public user base, the site is still useful as a personal research log.
You can collect links, papers, manuals, code, datasets, talks, questions, and notes in one place.
You can write short explanations of your own work and share clean public URLs.
You can keep a private saved list of things to read or revisit.
You can use the personal HTML page as a lightweight academic homepage.
You can create a private lab/seminar/friend community and use it as a shared reading/discussion space.
You can run simple bot/user accounts that post links into a community, such as a /c/nature feed.
So the product does not need global discussion on day one. It starts as a lightweight research log, personal page, and small-group discussion tool; if enough people use it, the same objects become the public HN-like research site.


# Key design rule

Keep the site conceptually simple:

submissions are the things
comments discuss the things
communities are views over the things
scopes decide visibility
moderation is global or community-local for submissions
users are pseudonymous, not scored
personal pages are owned spaces
everything works as plain server-rendered HTML
