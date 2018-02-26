# mccdl - Minecraft Curse Downloader

## Summary

mccdl is a script that downloads modpacks from Minecraft CurseForge and
creates a MultiMC instance from them.

## Features

* Given a modpack URL and instance name, mccdl creates a full MultiMC instance for you!
  This includes configuring MultiMC to download the correct version of Minecraft and
  Forge. You don't need to do anything afterwards except open MultiMC and click launch.
* You can select which version of a pack you want by passing a link to the download for
  a particular version. If no particular version is provided, the latest version of the
  pack is downloaded.
* If a manifest references a mod version that no longer exists on Curse, mccdl will find
  the next published file from the same mod (and Minecraft version) and download that,
  instead.
* For newly created instances, mccdl will pull the icon from the modpack.
* mccdl can upgrade your modpack instances (**BACK UP your instance before doing this!**).
* mccdl caches downloads to save bandwidth. Your Comcast data cap will thank you... those
  jerks.
* Cleaner code than some other options. Maybe that matters to you, maybe not!

## Why another Curse pack downloader?

There are a few reasons why I chose to write another instead of contribute
to something existing. The first is that this was a learning experience,
and I value those. The second is that I'm pretty anal about code -- if I
do it myself, I've only myself to blame. The third is that I thought I
could do it better and with more features.

## How do I use this thing?

You need just a few things to make use of this script:

    * python 3.6+ (this will be lowered to 3.4+ shortly)
    * virtualenv for python
    * MultiMC 0.5.0 (that's where the instances end up)
    * git (to clone the repository)

After cloning the repository, just run `./mccdl $MODPACK_URL $MULTIMC_INSTANCE_NAME`
and after a while you should have a brand new instance in MultiMC.

Replace `$MODPACK_URL` by the URL to the modpack you want to download. The URL
**must be a Curse URL**. Any URL starting with "minecraft.curseforge.com" or
"mods.curse.com" is acceptable. A URL starting with "feed-the-beast.com" is not,
and it won't be supported (use the "View on Curse.com" link if needed).

Replace `$MULTIMC_INSTANCE_NAME` by the name of the MultiMC instance to create.
It's okay to use spaces, but you need to quote or escape appropriately (you
know how to use the shell, right? :-) ).

If in doubt, you can always use `./mccdl --help`!

There is no GUI and I'm not terribly interested in creating one, but if someone
contributed some quality code to that end, I'd happily take it.

## How do I ask for help?

OK - I'm gonna level with you guys. I don't really have the time nor inclination
to teach people how to use this. If you've ever checked out a repository on GitHub
and used the shell before it should be *very* straightforward. Please don't blow
up the GitHub issue page with support requests.

## How do I request new features or report a bug?

Now we're talking! If you can think of an interesting feature that is not loads of
work to implement vs. the benefits it brings, I'd love to hear about it via GitHub
issue.

Likewise, if you find a bug and have at least read through "How do I use this thing?",
file an issue. That said, there are some ground rules:

* Include in **EVERY BUG REPORT**:
    * the revision of mccdl where your bug occurred
    * the version of MultiMC you are using
    * steps to reproduce the bug (be detailed)
    * what you expected to happen (be detailed)
    * what actually happened instead (be detailed)
    * anything else you think might be relevant
* Don't abuse the issue tracker with tech support requests.
