# Google Cloud Condom

The cost of raising a child ranges from $233,610 to $284,570 for middle-income families in the United States. And [you get a child!](https://www.goodreads.com/book/show/10266902-selfish-reasons-to-have-more-kids). The same amount of money I would spend if I accidentally left my [innocent-seeming experiment](https://www.reddit.com/r/googlecloud/comments/14a3epc/post_mortem_how_i_was_charged_4000_eur_for/) with Google Cloud running for 2-3 weeks. [And what are the universities thinking? They go out of their way to ensure their students are well supplied with contraceptives, and yet they're hosting cloud tutorials and giving out student cloud credits left and right.](https://youtu.be/ii1jcLg-eIQ?t=988)

I am here with a solution. Google Cloud Condom is a Google Cloud Function that will automatically shut down your project(s) when you reach your budget limit and prevent further spending. 

*Warning 1*. Condom shuts down your projects by disabling their billing. This can and almost certainly *will lead to irreversible data loss*. Condom is meant for people who prefer irreversible data loss to irreversible financial loss. Condom only gets activated when 100% of your budget is reached and it is possible to set up budget alerts for 50%, 75% or any other percentage of the budget. It is recommended that you set up an alert for 30% or even lower so that you can get an alert and pull out gracefully.

*Warning 2* Google's budget alerts can arrive with a delay. Condom caps your spending at 100% of the budget + spending that occured during the alert delay. No protection is perfect.

*Warning 3* If you set up a budget for a particular project or set of projects and that budget is reached, the current version of Condom will still shut down all projects in your billing account. We are working on this. At the meantime, just don't connect project-specific budgets to Condom's pub/sub topic (see below)

## Installation

1. Create a google cloud project for Condom to run in. Note it's `PROJECT_ID`
2. [Create a budget](https://cloud.google.com/billing/docs/how-to/budgets) in your [Google Cloud Billing Account](https://console.cloud.google.com/billing). Condom is not responsible for managing your budgets. What Condom does is  shut down all projects that are linked to the budget you have set up when one is reached. You can set up budgets for any projects and billing accounts, they don't have to be related to PROJECT.
3. When setting up a budget make sure to tick the "Connect a Pub/Sub topic to this budget" box and choose the following topic `projects/PROJECT/topics/budgetreached`
4. Clone this repository
5. Make sure you have [google cloud CLI](https://cloud.google.com/sdk/docs/install) installed
6. Run

```
./deploy PROJECT_ID
```

7. Enjoy your time with Google Cloud.

*Note* It is allowed and intended to have many budgets connected to the same topic. When a budget is reached, a message is published on the topic with all the details of that budget. Condom will evaluate the blast radius of projects linked to that particular budget and shut them down. You only need to do one deployment per topic and the intended use case is having one Condom for all of you billing accounts.