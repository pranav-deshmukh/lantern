(function () {
  "use strict";

  angular.module("legacyJiraBoard").factory("BoardApi", function ($http, $q, $timeout) {
    var cache = null;

    function clone(value) {
      return JSON.parse(JSON.stringify(value));
    }

    function loadBoard() {
      if (cache) {
        return $q.resolve(clone(cache));
      }

      return $http.get("data/board.json").then(function (response) {
        cache = response.data;
        return clone(cache);
      });
    }

    function saveIssue(issue) {
      return $timeout(function () {
        if (!cache) {
          return issue;
        }

        cache.issues = cache.issues.map(function (existing) {
          return existing.id === issue.id ? clone(issue) : existing;
        });
        return clone(issue);
      }, 250);
    }

    function moveIssue(issueId, targetStatus) {
      return loadBoard().then(function (board) {
        var issue = board.issues.find(function (candidate) {
          return candidate.id === issueId;
        });

        if (!issue) {
          return $q.reject(new Error("Issue not found: " + issueId));
        }

        issue.status = targetStatus;
        return saveIssue(issue);
      });
    }

    return {
      loadBoard: loadBoard,
      moveIssue: moveIssue,
      saveIssue: saveIssue
    };
  });
})();
