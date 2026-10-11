(function () {
  "use strict";

  angular.module("legacyJiraBoard").filter("byStatus", function () {
    return function (issues, status) {
      return (issues || []).filter(function (issue) {
        return issue.status === status;
      });
    };
  });

  angular.module("legacyJiraBoard").filter("issueSearch", function () {
    return function (issues, filters) {
      var query = (filters.query || "").toLowerCase();
      var assignee = filters.assignee;

      return (issues || []).filter(function (issue) {
        var matchesAssignee = !assignee || issue.assigneeId === assignee;
        var haystack = [issue.key, issue.title, issue.summary, issue.type].join(" ").toLowerCase();
        return matchesAssignee && (!query || haystack.indexOf(query) !== -1);
      });
    };
  });
})();
