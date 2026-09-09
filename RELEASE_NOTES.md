# _Sharly Chess_ release notes

## General

- Significantly improved speed of the application (5.0.0)
- Reorganize the desktop application into tabs (5.0.0)
- Card-based administration pages now offer a compact list view with key information in columns and expandable details (5.0.0)
- Added federation CUR (5.0.0)
- Fix data recovery from previous 4.2.8 version (5.0.1)
- Fix place cards documents (5.0.1)
- The edit pencil on editable table columns is now always visible instead of only appearing on hover (5.0.3)
- Fix error status not cleared after reauthentication with Sharly-Chess.com (5.0.3)
- Fix _Papi_ export to no longer warns that tie-break values will be missing on the _FFE_ website when the points criterion leads the ranking (5.0.3)

## Events

- Custom tags can be created and added to events for easier filtering (5.0.0)
- Event creation allowed for access level "Organization" (5.0.0)
- Staff members can now be assigned as arbiters, separately from chief and deputy arbiter roles, and are included in tournament documents and _Chess-Results_ exports (5.0.0)
- Events whose name contains special characters (such as `&`) now upload to _Chess-Results_ correctly (5.0.0)
- A clear indication is now given in the case that an event file becomes locked by another application (anti-virus, synchronization, etc.) (5.0.3)

## Players

- Players now have separate _FIDE_ titles for the open and women titles, so a player can hold both at once (for example IM and WIM) (5.0.0)
- Titles are displayed intelligently: both are shown when they matter (e.g. FM and WIM), but the women title is hidden when the open title supersedes it (e.g. GM instead of GM/WGM) (5.0.0)
- When the _FIDE_ database is installed locally, players looked up from it (including via an _FFE_ search) have their women title filled in automatically (5.0.0)
- A player's record now shows their federation identifiers — the _FIDE_ ID, and the _FFE_ licence number for French events — each linking to the corresponding federation profile page (5.0.0)
- Omit empty lines when importing players (5.0.0)
- The player search results now close when clicking outside them (5.0.2)
- When creating several players in a row, only the tournament and team are carried over to the next player; the other fields start empty (5.0.2)
- Fix: searching or importing players no longer crashes when the local _FIDE_ database has not yet been updated to the version 5 format (5.0.3)

## Teams

- _Sharly Chess_ now supports **Teams** events (Swiss, Round-Robin, Scheveningen and Molter pairings)! (5.0.0)
- The match points scored by an absent team can now be set (5.0.4)
- The team ranking counts forfeited matches in a new **F** column (5.0.4)
- Fix: Molter tournaments no longer ask for match-point values they never use (5.0.4)
- Fix: the lineup editor groups the rounds sharing a lineup again (5.0.4)
- Fix: a round taking the previous round's lineup now takes the one it played (5.0.4)

## Championships

- _Sharly Chess_ now supports **Championships** which allow you generate a ranking from a set of independent tournaments (5.0.0)

## Pairings

- A new **Custom accelerated system** lets the arbiter define the acceleration round by round — a number of virtual points granted to a range of pairing numbers over a range of rounds — instead of choosing a published system (5.0.0)
- Tournaments using it export their rules as TRF26 250 records, and a TRF file carrying 250 records is now imported as a custom accelerated tournament (the **Accelerated pairings** plugin must be enabled) (5.0.0)
- A new **Initial score accelerated system** gives each player an initial virtual score — useful when a tournament continues an earlier one (a blitz, for instance). The scores can be filled in one go from any other tournament, in this event or another one, with a coefficient. (5.0.0)
- The **Keizer** pairing system has been added - perfect for club tournaments where players don't have to be available for each round (5.0.0)
- Pairing settings can be prepared before pairing round #1 and always reviewed (5.0.0)
- Warn when top acceleration groups have an odd number of players at round #1 (5.0.0)
- Fixed a bug concerning the hanling of the player's own keizer score (5.0.2)
- Fix: the pairing-system warning icon in the tournament list view now shows its explanation on hover (5.0.3)
- Display a clearer error message when the pairing engine fails to produce pairings (5.0.3)

## Rankings

- The points are now a ranking criterion in their own right, listed alongside the tie-breaks (5.0.0)
- Bonus / penalty points can be given to players (TRF26 299 record) (5.0.0)

## Fixed tables

The handling of fixed tables has been improved in several ways:

- The tables that the players would have been assigned to are no longer left empty (5.0.0)
- You can now assign any table number as a fixed table without having a duplicate table appearing (5.0.0)
- Changing fixed table assignment mid-tournament is now correctly handled (previous round table assignments are kept) (5.0.0)
- In the admin pairings view you can choose to sort by pairing order or board number (5.0.0)
- In the associated document view you can choose if fixed tables are ordered by pairing order or board number (5.0.0)
- Pairing screens now have option to order by pairing order or board number (5.0.0)
- Improved the display of fixed table numbers (5.0.3)

### Special considerations when using the _FFE_ (French federation) plugin

In order to maintain compatibility with the display of table numbers on the _FFE_ website:
- By default, we still leave the orignal table empty when the players are moved to a fixed table number (5.0.0)
- In this compatibility mode, duplicate tables still occur when fixed table numbers are inside the normal table range (5.0.0)
- This behavior can be changed in the _FFE_ plugin section of event's configuration (5.0.0)

## Prizes

- Added a quick way to generate prize categories for age categories and rating ranges (5.0.0)
- Duplication prize categories are now added immediately after the original (5.0.0)
- Duplicate prizes when duplicating a tournament (5.0.0)
- A monetary value can now be attached to the non-monetary part of a hybrid prize (e.g. the worth of a trophy) (5.0.0)

## Screens

- Menu support has been completely redesigned for a better experience (5.0.0)
- Screen families have been renamed **Multi-Screens** (5.0.0)
- Check-in screens now correctly use the configure column count (5.0.0)
- Vertical lines are now displayed between columns (5.0.0)
- A new **Chess 960** plugin allows you to display start positions for each round (5.0.0)
- Fixed access to rotators and display controllers from the network (5.0.2)
- Base clients on the server date to display the timers (5.0.3)
- Improved timer display (5.0.3)
- Network clients can now open screens, rotators, and display controllers by clicking anywhere on their card or list row (5.0.3)

## Documents

- Norm reports generated before the end of the tournament now assume that players will play the remaining rounds for the purposes of displaying 1.5.6a and 1.4.3d (5.0.0)
- Title norm calculations now take women titles into account: opponents holding a WGM or WIM title are correctly counted towards the 1.4.5 and 1.4.3d requirements, even when they also hold an open title (5.0.0)
- The pairings document now has an option to include a federation column (5.0.0)
- Upload documents to a custom location thanks to new plugin **Custom upload** (5.0.0)
