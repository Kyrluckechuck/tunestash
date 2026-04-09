import { gql } from '@apollo/client';

export const GetTaskHistoryDocument = gql`
  query GetTaskHistory(
    $page: Int = 1
    $pageSize: Int = 50
    $status: String
    $type: String
    $entityType: String
    $search: String
  ) {
    taskHistory(
      page: $page
      pageSize: $pageSize
      status: $status
      type: $type
      entityType: $entityType
      search: $search
    ) {
      pageInfo {
        page
        pageSize
        totalPages
        totalCount
      }
      items {
        id
        taskId
        type
        entityId
        entityType
        status
        startedAt
        completedAt
        durationSeconds
        progressPercentage
        logMessages
      }
    }
  }
`;
